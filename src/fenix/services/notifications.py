"""Telegram Bot API adapter; console output is development-only."""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import os
import re

import requests

from fenix.utils.errors import PermanentError, RetryableError


_TOKEN = re.compile(r"[A-Za-z0-9:_-]{16,256}\Z")


def _retry_after(value: str | None) -> int | None:
    if not value:
        return None
    try:
        seconds = int(value)
    except ValueError:
        try:
            target = parsedate_to_datetime(value)
            if target.tzinfo is None:
                return None
            seconds = int((target.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None
    return min(30, max(0, seconds))


def notify(text: str) -> None:
    """Send one Telegram message and classify the response for SQS retry."""
    mode = os.getenv("NOTIFY_PROVIDER", "console")
    message = text[:1000] if isinstance(text, str) else ""
    if mode == "console":
        print(message)
        return
    if mode != "telegram":
        raise PermanentError("NOTIFY_PROVIDER must be console or telegram")

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not _TOKEN.fullmatch(token) or not chat_id or len(chat_id) > 128:
        raise PermanentError("Telegram notification configuration is incomplete")
    endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        response = requests.post(
            endpoint,
            json={"chat_id": chat_id, "text": message},
            timeout=(2, 5),
            allow_redirects=False,
        )
    except requests.Timeout as error:
        raise RetryableError("Telegram request timed out") from error
    except requests.ConnectionError as error:
        raise RetryableError("Telegram connection failed") from error
    except requests.RequestException as error:
        raise PermanentError("Telegram request could not be constructed") from error

    status = response.status_code
    if status == 429:
        raise RetryableError(
            "Telegram rate limit reached",
            retry_after=_retry_after(response.headers.get("Retry-After")),
        )
    if 500 <= status <= 599:
        raise RetryableError(
            "Telegram service is temporarily unavailable",
            retry_after=_retry_after(response.headers.get("Retry-After")),
        )
    if not 200 <= status <= 299:
        raise PermanentError("Telegram rejected the notification request")
    try:
        payload = response.json()
    except ValueError as error:
        raise PermanentError("Telegram returned an invalid response") from error
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise PermanentError("Telegram did not confirm the notification")
