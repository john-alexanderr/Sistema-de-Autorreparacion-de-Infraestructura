"""Pruebas de rotación, legibilidad de gzip, marcas de tiempo UTC y redacción de registros."""

import gzip
import json
import logging
from threading import Event, Thread

import pytest

from fenix.utils.logging_json import JSONFormatter, setup


@pytest.mark.base
def test_json_formatter_emits_latency_ms_or_null_when_not_applicable():
    record = logging.LogRecord("formatter-test", logging.INFO, __file__, 1, "test", (), None)
    formatter = JSONFormatter()

    assert json.loads(formatter.format(record))["latency_ms"] is None

    record.latency_ms = 42.5
    assert json.loads(formatter.format(record))["latency_ms"] == 42.5


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


@pytest.mark.base
def test_listener_stop_flushes_records_waiting_in_the_queue(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    logger, listener = setup("listener-stop-test")
    sink = listener.handlers[0]
    emit_started = Event()
    release_emit = Event()
    sentinel_enqueued = Event()
    original_emit = sink.emit
    original_enqueue_sentinel = listener.enqueue_sentinel

    def blocked_emit(record):
        emit_started.set()
        assert release_emit.wait(timeout=5)
        original_emit(record)

    def observe_sentinel_enqueue():
        original_enqueue_sentinel()
        sentinel_enqueued.set()

    monkeypatch.setattr(sink, "emit", blocked_emit)
    monkeypatch.setattr(listener, "enqueue_sentinel", observe_sentinel_enqueue)
    messages = [f"queued record {index}" for index in range(12)]
    stop_thread = None
    try:
        logger.info(messages[0])
        assert emit_started.wait(timeout=5)
        for message in messages[1:]:
            logger.info(message)

        stop_thread = Thread(target=listener.stop)
        stop_thread.start()
        assert sentinel_enqueued.wait(timeout=5)
        release_emit.set()
        stop_thread.join(timeout=5)
        assert not stop_thread.is_alive()
    finally:
        release_emit.set()
        if stop_thread is None:
            listener.stop()
        else:
            stop_thread.join(timeout=5)

    log_file = next((tmp_path / "logs").glob("listener-stop-test-*.jsonl"))
    rows = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]
    assert [row["message"] for row in rows] == messages
