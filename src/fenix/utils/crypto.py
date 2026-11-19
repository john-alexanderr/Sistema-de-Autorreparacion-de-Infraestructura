"""Timestamped HMAC-SHA256 signing and verification."""

import hashlib
import hmac
import re
import time

from fenix.utils.errors import ValidationError


_HEADER = re.compile(r"t=([0-9]+),v1=([0-9a-fA-F]{64})\Z")


def _digest(secret: str, timestamp_bytes: bytes, body: bytes) -> str:
    signed = timestamp_bytes + b"." + body
    return hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()


def signature(secret: str, timestamp: int, body: bytes) -> str:
    """Sign the decimal timestamp, a dot, and the exact body bytes."""
    if not isinstance(secret, str) or len(secret) < 16:
        raise ValidationError("WEBHOOK_SECRET must contain at least 16 characters")
    if type(timestamp) is not int or timestamp < 0 or not isinstance(body, bytes):
        raise ValidationError("Invalid signature input")
    return _digest(secret, str(timestamp).encode("ascii"), body)


def verify(secret: str, header: str, body: bytes, now: int | None = None) -> None:
    """Verify the exact header syntax, timestamp window, and HMAC securely."""
    if not isinstance(secret, str) or len(secret) < 16:
        raise ValidationError("Webhook signature is invalid")
    if not isinstance(header, str) or not isinstance(body, bytes):
        raise ValidationError("Webhook signature is invalid")
    match = _HEADER.fullmatch(header)
    if match is None:
        raise ValidationError("Webhook signature is invalid")
    timestamp_text, supplied = match.groups()
    try:
        timestamp = int(timestamp_text)
    except ValueError as error:
        raise ValidationError("Webhook signature is invalid") from error
    current = int(time.time()) if now is None else now
    if type(current) is not int or abs(current - timestamp) > 300:
        raise ValidationError("Webhook signature is invalid")
    expected = _digest(secret, timestamp_text.encode("ascii"), body)
    if not hmac.compare_digest(expected, supplied.lower()):
        raise ValidationError("Webhook signature is invalid")
