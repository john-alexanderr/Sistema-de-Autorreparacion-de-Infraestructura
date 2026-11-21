"""Send one Telegram message and write privacy-safe confirmation evidence.

The script uses the production notification adapter, so a successful file proves
that ``fenix.services.notifications.notify`` confirmed ``ok: true`` with the Bot
API. It never prints or stores message text, message IDs, credentials, or API URLs.

Configuration is read from the process environment or the repository ``.env``:

* ``NOTIFY_PROVIDER=telegram``
* ``TELEGRAM_BOT_TOKEN``
* ``TELEGRAM_CHAT_ID``

Run from the repository root::

    ./.venv/bin/python scripts/telegram_evidence.py
    ./.venv/bin/python scripts/telegram_evidence.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dotenv import load_dotenv

from fenix.services.notifications import notify
from fenix.utils.errors import ProjectError


DEFAULT_OUT_DIR = ROOT / "evidencias" / "telegram"


def _utc_now() -> str:
    """Return an ISO-8601 UTC timestamp with a trailing Z."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _build_message() -> str:
    """Build a non-sensitive, uniquely identifiable evidence message."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"Fenix Telegram evidence | {stamp} | {uuid4().hex[:8]}"


def _configuration_error() -> str | None:
    """Return a sanitized configuration error, or None when ready."""
    provider = os.getenv("NOTIFY_PROVIDER", "").strip().lower()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if provider != "telegram":
        return "set NOTIFY_PROVIDER=telegram in .env or the shell"
    if not token:
        return "set TELEGRAM_BOT_TOKEN in .env or the shell"
    if not chat_id:
        return "set TELEGRAM_CHAT_ID in .env or the shell"
    if len(token) < 16:
        return "TELEGRAM_BOT_TOKEN is malformed"
    if len(chat_id) > 128:
        return "TELEGRAM_CHAT_ID is malformed"
    return None


def _evidence_path(out_dir: Path) -> Path:
    """Return a unique, timestamped evidence path."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    return out_dir / f"{stamp}_{uuid4().hex[:6]}_F02_telegram-evidence.json"


def _resolve_out_dir(value: str) -> Path | None:
    """Resolve an output directory only when it remains inside this checkout."""
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = DEFAULT_OUT_DIR / candidate
    try:
        repository_root = ROOT.resolve()
        evidence_root = DEFAULT_OUT_DIR.resolve()
        candidate = candidate.resolve()
        evidence_root.relative_to(repository_root)
        candidate.relative_to(evidence_root)
        candidate.relative_to(repository_root)
    except (OSError, RuntimeError, ValueError):
        return None
    return candidate


def _build_evidence() -> dict:
    """Build a confirmation record without message or provider identifiers."""
    return {
        "captured_at_utc": _utc_now(),
        "provider": "telegram",
        "status": "sent",
        "evidence_id": "F02",
        "command": "./.venv/bin/python scripts/telegram_evidence.py",
        "telegram_response": {"ok": True},
        "notes": [
            "Confirmation is recorded without message IDs or sent text.",
        ],
    }


def main(argv=None) -> int:
    """Send the message, write redacted evidence, and return an exit code."""
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(
        description="Send one Telegram message and write privacy-safe evidence.",
    )
    parser.add_argument(
        "--text",
        default=None,
        help="Message text to send; it is not included in output or evidence.",
    )
    parser.add_argument(
        "--out-dir",
        default=str(DEFAULT_OUT_DIR),
        help="Directory under evidencias/telegram for the evidence file.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration without sending or writing evidence.",
    )
    args = parser.parse_args(argv)

    configuration_error = _configuration_error()
    if configuration_error is not None:
        print(f"Telegram configuration incomplete: {configuration_error}", file=sys.stderr)
        return 2
    if args.dry_run:
        print(
            "Telegram configuration OK "
            "(provider=telegram, token=<redacted>, chat_id=<redacted>)."
        )
        return 0

    out_dir = _resolve_out_dir(args.out_dir)
    if out_dir is None:
        print(
            "Evidence output directory must be within evidencias/telegram.",
            file=sys.stderr,
        )
        return 2

    text = (args.text or _build_message())[:1000]
    try:
        result = notify(text, return_result=True)
    except ProjectError as error:
        print(f"Telegram send failed ({type(error).__name__}).", file=sys.stderr)
        return 1
    if not isinstance(result, dict) or result.get("ok") is not True:
        print("Telegram did not confirm ok=true", file=sys.stderr)
        return 1

    evidence_path = _evidence_path(out_dir)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(
            json.dumps(_build_evidence(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as error:
        print(f"Cannot write evidence file ({type(error).__name__}).", file=sys.stderr)
        return 1

    print("Telegram evidence captured.")
    print("Status: confirmed (provider=telegram, ok=true).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
