"""Errores de dominio saneados que comparten los servicios de la aplicación."""


class ProjectError(Exception):
    """Clase base para los fallos previstos de la aplicación."""


class ValidationError(ProjectError):
    """Los datos de entrada o del inventario incumplen un contrato explícito."""


class RetryableError(ProjectError):
    """Fallo transitorio por el que el mensaje debe quedar disponible en SQS."""

    def __init__(self, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class PermanentError(ProjectError):
    """Fallo de dominio no reintentable; el mensaje se conserva hasta que SQS lo redirija."""
