"""Registro estructurado en JSON con archivos rotativos acotados y archivos gzip."""
import gzip
import json
import logging
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
import os
import queue
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

_SIGNATURE = re.compile(r"t=[0-9]+,v1=[0-9a-fA-F]{64}")
_HEX_DIGEST = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])")
_URL = re.compile(r"https?://[^\s\"']+")


def _safe_message(message: str) -> str:
    message = _URL.sub("[REDACTED_URL]", message)
    message = _SIGNATURE.sub("[REDACTED_SIGNATURE]", message)
    return _HEX_DIGEST.sub("[REDACTED_SIGNATURE]", message)

class JSONFormatter(logging.Formatter):
    """Serializa únicamente los campos aprobados en lugar de copiar el registro completo.

    Notas:
        Cada proceso escribe en su propio archivo para evitar la rotación concurrente.
    """
    def format(self, record: logging.LogRecord) -> str:
        """Da formato a un registro como una línea JSON con marca de tiempo UTC.

        Argumentos:
            record: Registro con campos de contexto públicos opcionales.
        Devuelve:
            Una línea JSON con la marca de tiempo, el nivel, el mensaje y el contexto seguro.
        Errores:
            TypeError: Si un valor de contexto aprobado no se puede serializar como JSON.
        """
        data = {"timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
                "level": record.levelname, "message": _safe_message(record.getMessage()),
                "process": record.process, "thread": record.threadName}
        for name in (
            "event_id",
            "message_id",
            "resource_id",
            "attempt",
            "action",
            "status",
            "latency_ms",
        ):
            data[name] = getattr(record, name, None)
        return json.dumps(data, ensure_ascii=False)


def gzip_name(name: str) -> str:
    """Devuelve el nombre de un archivo gzip para un registro rotado.

    Argumentos:
        name: Nombre de archivo propuesto por RotatingFileHandler.
    Devuelve:
        El nombre propuesto con el sufijo .gz.
    """
    return name + ".gz"


def gzip_rotate(source: str, dest: str) -> None:
    """Comprime un archivo cerrado y elimina su origen sin comprimir.

    Argumentos:
        source: Archivo cerrado por el controlador de rotación.
        dest: Ruta de destino del archivo gzip.
    Devuelve:
        None.
    Errores:
        OSError: Si falla la lectura, la compresión o la eliminación del archivo de origen.
    Notas:
        En esta implementación, la publicación del archivo gzip no es atómica.
    """
    with open(source, "rb") as origin, gzip.open(dest, "wb") as target:
        shutil.copyfileobj(origin, target)
    os.remove(source)


def setup(
    name: str,
    max_bytes: int = 2 * 1024 * 1024,
    backup_count: int = 3,
) -> tuple[logging.Logger, QueueListener]:
    """Inicia un flujo de registro JSON respaldado por un archivo específico del proceso.

    Argumentos:
        name: Nombre público del componente, por ejemplo fenix-worker.
        max_bytes: Umbral de rotación; configurable para pruebas deterministas.
        backup_count: Cantidad de archivos comprimidos que se conservarán.
    Devuelve:
        El logger y el listener; quien realiza la llamada debe ejecutar listener.stop durante la limpieza.
    Errores:
        OSError: Si no se puede crear el directorio o el archivo de registros.
    Efectos secundarios:
        Inicia un hilo listener y abre un controlador de archivos rotativos; se debe llamar una vez por proceso.
    """
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    if type(backup_count) is not int or backup_count < 0:
        raise ValueError("backup_count must be a non-negative integer")
    Path("logs").mkdir(exist_ok=True)
    sink = RotatingFileHandler(
        f"logs/{name}-{os.getpid()}.jsonl",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    sink.setFormatter(JSONFormatter())
    sink.namer, sink.rotator = gzip_name, gzip_rotate
    records = queue.Queue()
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    logger.propagate = False
    logger.addHandler(QueueHandler(records))
    listener = QueueListener(records, sink)
    listener.start()
    return logger, listener
