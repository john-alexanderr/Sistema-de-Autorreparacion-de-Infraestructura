"""Rotation, gzip readability, UTC timestamps, and log redaction tests."""

import gzip
import json

import pytest

from fenix.utils.logging_json import setup


@pytest.mark.base
def test_small_threshold_rotates_to_readable_gzip_json_without_secrets(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    logger, listener = setup("rotation-test", max_bytes=220, backup_count=6)
    private_url = "https://api.telegram.org/bot123456:private-token/sendMessage"
    signature = "t=1795000000,v1=" + "a" * 64
    try:
        logger.debug("debug fixture")
        logger.info("request failed at " + private_url)
        logger.warning("invalid signature " + signature)
        logger.error("controlled error fixture")
        logger.critical("critical test fixture only")
    finally:
        listener.stop()

    log_dir = tmp_path / "logs"
    archives = sorted(log_dir.glob("*.gz"))
    assert archives
    rows = []
    for archive in archives:
        with gzip.open(archive, "rt", encoding="utf-8") as stream:
            rows.extend(json.loads(line) for line in stream)
    for active in log_dir.glob("*.jsonl"):
        rows.extend(json.loads(line) for line in active.read_text(encoding="utf-8").splitlines())

    levels = {row["level"] for row in rows}
    assert {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}.issubset(levels)
    assert all(row["timestamp"].endswith("+00:00") for row in rows)
    serialized = json.dumps(rows)
    assert private_url not in serialized
    assert "private-token" not in serialized
    assert "a" * 64 not in serialized
