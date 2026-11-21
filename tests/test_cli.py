"""Pruebas sin conexión del análisis de argumentos, el envío y la limpieza de la CLI de Fénix."""

import json
from unittest.mock import Mock

import pytest

from fenix import cli
from fenix.utils.crypto import signature


@pytest.mark.base
def test_invalid_arguments_exit_before_logger_or_network_work(monkeypatch):
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(cli.sys, "argv", ["fenix", "unknown-command"])

    boundaries = [
        Mock(name="logging_setup"),
        Mock(name="http_post"),
        Mock(name="ensure_queues"),
        Mock(name="setup_demo"),
        Mock(name="inject_fault"),
        Mock(name="queue_url"),
        Mock(name="worker_run"),
    ]
    monkeypatch.setattr(cli, "setup", boundaries[0])
    monkeypatch.setattr(cli.requests, "post", boundaries[1])
    monkeypatch.setattr(cli.sqs, "ensure_queues", boundaries[2])
    monkeypatch.setattr(cli.demo, "setup_demo", boundaries[3])
    monkeypatch.setattr(cli.demo, "inject_fault", boundaries[4])
    monkeypatch.setattr(cli.sqs, "queue_url", boundaries[5])
    monkeypatch.setattr(cli.worker, "run", boundaries[6])

    with pytest.raises(SystemExit) as exit_info:
        cli.main()

    assert exit_info.value.code == 2
    assert all(not boundary.called for boundary in boundaries)


@pytest.mark.base
def test_send_signs_and_posts_exact_file_bytes_and_stops_listener(
    monkeypatch, tmp_path
):
    payload = b'{\n  "event_id": "evt-node-001",\n  "schema_version": 1\n}\n'
    event_file = tmp_path / "event.json"
    event_file.write_bytes(payload)
    timestamp = 1_900_000_000
    secret = "local-test-secret-with-enough-length"
    response = Mock(status_code=202, text="accepted")
    post = Mock(return_value=response)
    logger = Mock()
    listener = Mock()
    setup = Mock(return_value=(logger, listener))

    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(cli, "setup", setup)
    monkeypatch.setattr(cli.requests, "post", post)
    monkeypatch.setattr(cli.time, "time", lambda: timestamp)
    monkeypatch.setattr(cli.sys, "argv", ["fenix", "send", str(event_file)])
    monkeypatch.setenv("WEBHOOK_SECRET", secret)

    assert cli.main() == 0

    post.assert_called_once()
    request_args, request_kwargs = post.call_args
    assert request_args == ("http://127.0.0.1:8000/webhook",)
    assert request_kwargs["data"] == payload
    assert "json" not in request_kwargs
    assert request_kwargs["headers"]["X-Webhook-Signature"] == (
        f"t={timestamp},v1={signature(secret, timestamp, payload)}"
    )
    assert json.loads(request_kwargs["data"]) == json.loads(payload)
    listener.stop.assert_called_once_with()


@pytest.mark.base
def test_listener_stops_after_controlled_send_failure(monkeypatch, tmp_path):
    event_file = tmp_path / "event.json"
    event_file.write_bytes(b'{"event_id":"evt-node-001"}')
    logger = Mock()
    listener = Mock()
    setup = Mock(return_value=(logger, listener))
    post = Mock(side_effect=cli.requests.RequestException("local endpoint unavailable"))

    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(cli, "setup", setup)
    monkeypatch.setattr(cli.requests, "post", post)
    monkeypatch.setattr(cli.time, "time", lambda: 1_900_000_000)
    monkeypatch.setattr(cli.sys, "argv", ["fenix", "send", str(event_file)])
    monkeypatch.setenv("WEBHOOK_SECRET", "local-test-secret-with-enough-length")

    assert cli.main() == 1

    post.assert_called_once()
    logger.error.assert_called_once()
    listener.stop.assert_called_once_with()
