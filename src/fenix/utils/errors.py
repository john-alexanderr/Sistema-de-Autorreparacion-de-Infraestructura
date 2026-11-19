"""Sanitized domain errors shared by the application services."""


class ProjectError(Exception):
    """Base class for expected application failures."""


class ValidationError(ProjectError):
    """Input or inventory data violates an explicit contract."""


class RetryableError(ProjectError):
    """A transient failure that should leave the SQS message available."""

    def __init__(self, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class PermanentError(ProjectError):
    """A non-retryable domain failure retained until SQS redrives the message."""
