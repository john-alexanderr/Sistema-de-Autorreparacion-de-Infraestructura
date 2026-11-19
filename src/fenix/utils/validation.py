"""Strict validation helpers for the Fénix contracts."""

import re
from datetime import datetime, timedelta, timezone

from fenix.utils.errors import ValidationError


_IDENTIFIER = re.compile(r"[a-z0-9-]{3,32}\Z")
_DIGITS = re.compile(r"[0-9]+\Z")
_UTC_TEXT = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|\+00:00)\Z"
)


def identifier(value: str) -> str:
    """Return an unchanged identifier matching the project's closed format."""
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValidationError("Identifier must contain 3-32 lowercase letters, digits, or hyphens")
    return value


def ttl_seconds(value: str) -> int:
    """Parse a decimal TTL in the inclusive range 60-600 seconds."""
    if not isinstance(value, str) or _DIGITS.fullmatch(value) is None:
        raise ValidationError("TTL must be an integer between 60 and 600 seconds")
    try:
        ttl = int(value)
    except ValueError as error:
        raise ValidationError("TTL must be an integer between 60 and 600 seconds") from error
    if not 60 <= ttl <= 600:
        raise ValidationError("TTL must be an integer between 60 and 600 seconds")
    return ttl


def utc_text(value: str) -> datetime:
    """Parse an ISO-8601 timestamp that explicitly represents UTC."""
    if not isinstance(value, str) or _UTC_TEXT.fullmatch(value) is None:
        raise ValidationError("Timestamp must be an ISO-8601 UTC string")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ValidationError("Timestamp must be an ISO-8601 UTC string") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValidationError("Timestamp must include a UTC offset")
    return parsed.astimezone(timezone.utc)
