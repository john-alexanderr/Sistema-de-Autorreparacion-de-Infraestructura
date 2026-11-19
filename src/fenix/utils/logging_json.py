"""Structured JSON logging with bounded rotating files and gzip archives."""
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
    """Serialize only approved fields instead of copying the whole log record.

    Notes:
        Each process writes to its own file to avoid concurrent rotation.
    """
    def format(self, record: logging.LogRecord) -> str:
        """Format a record as one JSON line with a UTC timestamp.

        Args:
            record: Log record with optional public context fields.
        Returns:
            A JSON line containing the timestamp, level, message, and safe context.
        Raises:
            TypeError: If an approved context value is not JSON serializable.
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
    """Return a gzip archive name for a rotated log file.

    Args:
        name: Archive name proposed by RotatingFileHandler.
    Returns:
        The proposed name with a .gz suffix.
    """
    return name + ".gz"


def gzip_rotate(source: str, dest: str) -> None:
    """Compress a closed archive and remove its uncompressed source.

    Args:
        source: Archive file closed by the rotating handler.
        dest: Destination path for the gzip archive.
    Returns:
        None.
    Raises:
        OSError: If reading, compression, or source removal fails.
    Notes:
        Gzip publication is not atomic in this implementation.
    """
    with open(source, "rb") as origin, gzip.open(dest, "wb") as target:
        shutil.copyfileobj(origin, target)
    os.remove(source)


def setup(
    name: str,
    max_bytes: int = 2 * 1024 * 1024,
    backup_count: int = 3,
) -> tuple[logging.Logger, QueueListener]:
    """Start a JSON logging pipeline backed by a process-specific file.

    Args:
        name: Public component name, such as fenix-worker.
        max_bytes: Rotation threshold; configurable for deterministic tests.
        backup_count: Number of compressed archives to retain.
    Returns:
        Logger and listener; the caller must execute listener.stop in cleanup.
    Raises:
        OSError: If the logs directory or file cannot be created.
    Side Effects:
        Starts a listener thread and opens a rotating file handler; call once per process.
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
