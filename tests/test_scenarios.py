"""Offline worker, durable-ledger, Telegram, and retry scenario tests."""

import json
import logging

import pytest
import requests
from botocore.exceptions import ClientError

from fenix.services import notifications, remediation, sqs, worker
from fenix.utils.errors import PermanentError, RetryableError
from fenix.utils.state import load, save


def event(**overrides) -> dict:
    value = {
        "schema_version": 1,
        "event_id": "evt-node-001",
        "event_type": "instance.stopped",
        "resource_id": "node-01",
        "occurred_at": "2026-10-22T18:00:00Z",
        "simulate_failures": 0,
    }
    value.update(overrides)
    return value


def inventory() -> dict:
    tags = {
        "ManagedBy": "ppa2",
        "Project": "fenix",
        "GroupId": "grupo-01",
        "Owner": "grupo-01",
        "Name": "fenix-grupo-01-node",
    }
    return {
        "node-01": {
            "type": "ec2",
            "group_id": "grupo-01",
            "id": "i-test-001",
            "security_group_id": "sg-test-001",
            "expected_tags": tags,
            "status": "ready",
        }
    }


def configure_ledger(monkeypatch, tmp_path):
    inventory_path = tmp_path / "inventory.json"
    events_path = tmp_path / "events.json"
    save(str(inventory_path), inventory())
    monkeypatch.setattr(remediation, "INVENTORY_PATH", str(inventory_path))
    monkeypatch.setattr(remediation, "EVENTS_PATH", str(events_path))
    return events_path


@pytest.mark.base
def test_simulated_failures_persist_across_attempts_then_complete(monkeypatch, tmp_path):
    path = configure_ledger(monkeypatch, tmp_path)
    calls = {"repair": 0, "notify": 0}
    monkeypatch.setattr(remediation, "repair", lambda *_args: calls.__setitem__("repair", calls["repair"] + 1) or "repaired")
    monkeypatch.setattr(remediation, "notify", lambda _text: calls.__setitem__("notify", calls["notify"] + 1))

    target = event(simulate_failures=2)
    for expected_attempt in (1, 2):
        with pytest.raises(RetryableError):
            remediation.handle(target)
        assert load(str(path))[target["event_id"]]["attempts"] == expected_attempt
    remediation.handle(target)

    record = load(str(path))[target["event_id"]]
    assert record["attempts"] == 3
    assert record["repair_done"] is True
    assert record["notified"] is True
    assert record["status"] == "complete"
    assert calls == {"repair": 1, "notify": 1}


@pytest.mark.base
def test_duplicate_after_restart_does_not_repeat_completed_stages(monkeypatch, tmp_path):
    configure_ledger(monkeypatch, tmp_path)
    calls = {"repair": 0, "notify": 0}
    monkeypatch.setattr(remediation, "repair", lambda *_args: calls.__setitem__("repair", calls["repair"] + 1) or "already_ok")
    monkeypatch.setattr(remediation, "notify", lambda _text: calls.__setitem__("notify", calls["notify"] + 1))

    first_handler = remediation.handle
    first_handler(event())
    process_restart_handler = remediation.handle
    process_restart_handler(event())
    assert calls == {"repair": 1, "notify": 1}


@pytest.mark.base
def test_restart_after_repair_resumes_notification_only(monkeypatch, tmp_path):
    path = configure_ledger(monkeypatch, tmp_path)
    calls = {"repair": 0, "notify": 0}

    def repair_once(*_args):
        calls["repair"] += 1
        return "repaired"

    def notification_with_one_failure(_text):
        calls["notify"] += 1
        if calls["notify"] == 1:
            raise RetryableError("temporary notification failure", retry_after=4)

    monkeypatch.setattr(remediation, "repair", repair_once)
    monkeypatch.setattr(remediation, "notify", notification_with_one_failure)
    with pytest.raises(RetryableError):
        remediation.handle(event())
    between_stages = load(str(path))["evt-node-001"]
    assert between_stages["repair_done"] is True
    assert between_stages["notified"] is False
    remediation.handle(event())
    assert calls == {"repair": 1, "notify": 2}
    assert load(str(path))["evt-node-001"]["status"] == "complete"


@pytest.mark.base
def test_repair_converges_when_ledger_checkpoint_save_fails(monkeypatch, tmp_path):
    path = configure_ledger(monkeypatch, tmp_path)
    instance = {"state": "stopped", "start_calls": 0}
    notifications_sent = []

    class FakeEC2:
        def describe_instances(self, **_kwargs):
            tags = inventory()["node-01"]["expected_tags"]
            return {
                "Reservations": [
                    {
                        "Instances": [
                            {
                                "InstanceId": "i-test-001",
                                "State": {"Name": instance["state"]},
                                "Tags": [
                                    {"Key": key, "Value": value}
                                    for key, value in tags.items()
                                ],
                            }
                        ]
                    }
                ]
            }

        def start_instances(self, **_kwargs):
            instance["start_calls"] += 1
            instance["state"] = "running"
            return {}

    ec2 = FakeEC2()
    monkeypatch.setattr(remediation, "client", lambda _service: ec2)
    monkeypatch.setattr(remediation, "notify", notifications_sent.append)

    original_save = remediation.save
    checkpoint_failure = {"raised": False}

    def fail_repair_checkpoint_once(file_path, state):
        entry = state.get("evt-node-001") if isinstance(state, dict) else None
        if entry and entry.get("repair_done") is True and not checkpoint_failure["raised"]:
            checkpoint_failure["raised"] = True
            raise OSError("simulated ledger checkpoint failure")
        original_save(file_path, state)

    monkeypatch.setattr(remediation, "save", fail_repair_checkpoint_once)

    with pytest.raises(OSError, match="simulated ledger checkpoint failure"):
        remediation.handle(event())

    assert instance["state"] == "running"
    assert instance["start_calls"] == 1
    assert load(str(path))["evt-node-001"]["repair_done"] is False
    assert notifications_sent == []

    remediation.handle(event())

    final = load(str(path))["evt-node-001"]
    assert instance["start_calls"] == 1
    assert final["repair_done"] is True
    assert final["repair_result"] == "already_ok"
    assert final["notified"] is True
    assert final["status"] == "complete"
    assert len(notifications_sent) == 1


@pytest.mark.base
def test_conflicting_event_id_preserves_first_content_and_never_repairs_again(monkeypatch, tmp_path):
    path = configure_ledger(monkeypatch, tmp_path)
    repaired = []
    monkeypatch.setattr(remediation, "repair", lambda *_args: repaired.append(True) or "repaired")
    monkeypatch.setattr(remediation, "notify", lambda _text: None)
    original = event()
    remediation.handle(original)

    conflicting = event(occurred_at="2026-10-22T18:01:00Z")
    with pytest.raises(PermanentError):
        remediation.handle(conflicting)
    record = load(str(path))["evt-node-001"]
    assert record["content"] == original
    assert record["conflicts"] == [conflicting]
    assert record["status"] == "conflict"
    assert repaired == [True]


@pytest.mark.base
def test_worker_acknowledges_only_after_handler_success(monkeypatch):
    message = {
        "MessageId": "message-001",
        "ReceiptHandle": "receipt-current",
        "Body": json.dumps(event()),
        "Attributes": {"ApproximateReceiveCount": "1"},
    }
    calls = []
    monkeypatch.setattr(worker, "receive", lambda _url: [message])
    monkeypatch.setattr(worker, "acknowledge", lambda _url, receipt: calls.append(("ack", receipt)))
    monkeypatch.setattr(worker, "retry_later", lambda _url, _message: calls.append(("retry", None)) or 2)
    logger = logging.getLogger("worker-ack-test")

    def failing_handler(_event):
        calls.append(("handler", None))
        raise RetryableError("temporary")

    worker.run("queue", failing_handler, logger, once=True)
    assert calls == [("handler", None), ("retry", None)]

    calls.clear()
    worker.run("queue", lambda _event: calls.append(("handler", None)), logger, once=True)
    assert calls == [("handler", None), ("ack", "receipt-current")]


@pytest.mark.base
def test_worker_logs_acknowledged_status_with_correlation_fields(monkeypatch, caplog):
    message = {
        "MessageId": "message-001",
        "ReceiptHandle": "receipt-current",
        "Body": json.dumps(event()),
        "Attributes": {"ApproximateReceiveCount": "2"},
    }
    monkeypatch.setattr(worker, "receive", lambda _url: [message])
    monkeypatch.setattr(worker, "acknowledge", lambda *_args: None)
    logger = logging.getLogger("worker-ack-status-test")

    with caplog.at_level(logging.INFO, logger=logger.name):
        worker.run("queue", lambda _event: None, logger, once=True)

    records = [
        record
        for record in caplog.records
        if record.name == logger.name and record.getMessage() == "message_acknowledged"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.status == "acknowledged"
    assert record.event_id == "evt-node-001"
    assert record.message_id == "message-001"
    assert record.resource_id == "node-01"
    assert record.attempt == 2
    assert record.action == "acknowledge"


@pytest.mark.base
def test_worker_client_error_during_ack_is_logged_and_retained(monkeypatch, caplog):
    message = {
        "MessageId": "message-001",
        "ReceiptHandle": "receipt-current",
        "Body": json.dumps(event()),
        "Attributes": {"ApproximateReceiveCount": "1"},
    }
    class FailedDeleteSQS:
        calls = []

        def delete_message(self, **_kwargs):
            self.calls.append("delete")
            raise ClientError(
                {"Error": {"Code": "ServiceUnavailable", "Message": "do not log"}},
                "DeleteMessage",
            )

        def change_message_visibility(self, **kwargs):
            self.calls.append(("visibility", kwargs["VisibilityTimeout"]))

    monkeypatch.setattr(worker, "receive", lambda _url: [message])
    monkeypatch.setattr(sqs, "client", lambda _service: FailedDeleteSQS())
    logger = logging.getLogger("worker-ack-client-error-test")

    with caplog.at_level(logging.INFO, logger=logger.name):
        worker.run("queue", lambda _event: None, logger, once=True)

    records = [record for record in caplog.records if record.name == logger.name]
    failure = next(record for record in records if record.getMessage() == "message_acknowledgement_failed")
    assert failure.status == "ClientError"
    assert FailedDeleteSQS.calls == ["delete", ("visibility", 2)]
    assert not any(record.getMessage() == "message_acknowledged" for record in records)
    assert "do not log" not in failure.getMessage()


@pytest.mark.base
def test_worker_client_error_during_visibility_update_is_sanitized_and_loop_continues(
    monkeypatch, caplog
):
    message = {
        "MessageId": "message-001",
        "ReceiptHandle": "receipt-current",
        "Body": json.dumps(event()),
        "Attributes": {"ApproximateReceiveCount": "1"},
    }
    receive_calls = []

    def receive(_url):
        receive_calls.append(True)
        if len(receive_calls) == 1:
            return [message]
        if len(receive_calls) == 2:
            return []
        raise RuntimeError("stop after proving another poll")

    class FailedVisibilitySQS:
        calls = []

        def change_message_visibility(self, **_kwargs):
            self.calls.append("visibility")
            raise ClientError(
                {"Error": {"Code": "ServiceUnavailable", "Message": "private response"}},
                "ChangeMessageVisibility",
            )

        def delete_message(self, **_kwargs):
            self.calls.append("delete")

    monkeypatch.setattr(worker, "receive", receive)
    monkeypatch.setattr(sqs, "client", lambda _service: FailedVisibilitySQS())
    logger = logging.getLogger("worker-visibility-client-error-test")

    def fail_handler(_event):
        raise RetryableError("temporary")

    with caplog.at_level(logging.INFO, logger=logger.name):
        with pytest.raises(RuntimeError, match="proving another poll"):
            worker.run("queue", fail_handler, logger)

    failure = next(
        record
        for record in caplog.records
        if record.name == logger.name
        and record.getMessage() == "message_visibility_update_failed"
    )
    assert failure.status == "ClientError"
    assert FailedVisibilitySQS.calls == ["visibility"]
    assert len(receive_calls) == 3
    assert "private response" not in failure.getMessage()


@pytest.mark.base
def test_worker_keeps_running_after_poison_message(monkeypatch):
    poison = {
        "MessageId": "message-poison",
        "ReceiptHandle": "receipt-poison",
        "Body": "{invalid",
        "Attributes": {"ApproximateReceiveCount": "1"},
    }
    valid = {
        "MessageId": "message-valid",
        "ReceiptHandle": "receipt-valid",
        "Body": json.dumps(event()),
        "Attributes": {"ApproximateReceiveCount": "1"},
    }
    calls = []
    monkeypatch.setattr(worker, "receive", lambda _url: [poison, valid])
    monkeypatch.setattr(worker, "retry_later", lambda _url, message: calls.append(("retry", message["ReceiptHandle"])) or 2)
    monkeypatch.setattr(worker, "acknowledge", lambda _url, receipt: calls.append(("ack", receipt)))
    worker.run("queue", lambda _event: calls.append(("handler", None)), logging.getLogger("poison-test"), once=True)
    assert calls == [("retry", "receipt-poison"), ("handler", None), ("ack", "receipt-valid")]


@pytest.mark.base
@pytest.mark.parametrize("count,expected", [("1", 2), ("2", 4), ("3", 8), ("8", 30)])
def test_retry_later_changes_visibility_on_current_receipt(monkeypatch, count, expected):
    class FakeSQS:
        def change_message_visibility(self, **kwargs):
            self.kwargs = kwargs

    fake = FakeSQS()
    monkeypatch.setattr(sqs, "client", lambda _service: fake)
    message = {
        "ReceiptHandle": "most-recent-receipt",
        "Attributes": {"ApproximateReceiveCount": count},
    }
    assert sqs.retry_later("queue-url", message) == expected
    assert fake.kwargs["ReceiptHandle"] == "most-recent-receipt"
    assert fake.kwargs["VisibilityTimeout"] == expected


@pytest.mark.base
def test_retry_after_is_a_minimum_without_inner_retries(monkeypatch):
    message = {
        "MessageId": "message-001",
        "ReceiptHandle": "receipt-current",
        "Body": json.dumps(event()),
        "Attributes": {"ApproximateReceiveCount": "1"},
    }
    observed = []
    monkeypatch.setattr(worker, "receive", lambda _url: [message])
    monkeypatch.setattr(worker, "acknowledge", lambda *_args: observed.append("ack"))
    monkeypatch.setattr(
        worker,
        "retry_later",
        lambda _url, _message, minimum_delay=None: observed.append(("retry", minimum_delay)) or 4,
    )

    def fail_with_retry_after(_event):
        raise RetryableError("rate limited", retry_after=4)

    worker.run("queue", fail_with_retry_after, logging.getLogger("retry-after-test"), once=True)
    assert observed == [("retry", 4)]


@pytest.mark.base
def test_telegram_adapter_sends_json_and_requires_provider_confirmation(monkeypatch):
    monkeypatch.setenv("NOTIFY_PROVIDER", "telegram")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:abcdefghijklmnopqrstuvwxyz")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100123456")
    calls = []

    class Response:
        status_code = 200
        headers = {}

        def json(self):
            return {"ok": True, "result": {"message_id": 1}}

    def send(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(notifications.requests, "post", send)
    notifications.notify("repair complete")
    url, kwargs = calls[0]
    assert url.startswith("https://api.telegram.org/bot") and url.endswith("/sendMessage")
    assert kwargs["json"] == {"chat_id": "-100123456", "text": "repair complete"}
    assert "parse_mode" not in kwargs["json"]
    assert kwargs["timeout"] == (2, 5)
    assert kwargs["allow_redirects"] is False


@pytest.mark.base
@pytest.mark.parametrize("status", [400, 401, 403])
def test_telegram_client_errors_are_permanent(monkeypatch, status):
    monkeypatch.setenv("NOTIFY_PROVIDER", "telegram")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:abcdefghijklmnopqrstuvwxyz")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100123456")

    class Response:
        status_code = status
        headers = {}

    monkeypatch.setattr(notifications.requests, "post", lambda *_args, **_kwargs: Response())
    with pytest.raises(PermanentError):
        notifications.notify("repair complete")


@pytest.mark.base
def test_telegram_5xx_and_connection_failures_are_transient(monkeypatch):
    monkeypatch.setenv("NOTIFY_PROVIDER", "telegram")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:abcdefghijklmnopqrstuvwxyz")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100123456")

    class Unavailable:
        status_code = 503
        headers = {}

    monkeypatch.setattr(notifications.requests, "post", lambda *_args, **_kwargs: Unavailable())
    with pytest.raises(RetryableError):
        notifications.notify("repair complete")

    def disconnected(*_args, **_kwargs):
        raise requests.ConnectionError("connection details must not be logged")

    monkeypatch.setattr(notifications.requests, "post", disconnected)
    with pytest.raises(RetryableError):
        notifications.notify("repair complete")


@pytest.mark.base
@pytest.mark.parametrize("header,expected", [("12", 12), ("90", 30)])
def test_telegram_5xx_retry_after_is_propagated_and_bounded(monkeypatch, header, expected):
    monkeypatch.setenv("NOTIFY_PROVIDER", "telegram")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:abcdefghijklmnopqrstuvwxyz")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100123456")
    calls = []

    class Response:
        status_code = 503
        headers = {"Retry-After": header}

    def send(*_args, **_kwargs):
        calls.append(True)
        return Response()

    monkeypatch.setattr(notifications.requests, "post", send)
    with pytest.raises(RetryableError) as failure:
        notifications.notify("repair complete")

    assert failure.value.retry_after == expected
    assert failure.value.retry_after <= 30
    assert calls == [True]


@pytest.mark.base
def test_telegram_429_honors_bounded_retry_after_and_timeout_is_transient(monkeypatch):
    monkeypatch.setenv("NOTIFY_PROVIDER", "telegram")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:abcdefghijklmnopqrstuvwxyz")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100123456")

    class RateLimited:
        status_code = 429
        headers = {"Retry-After": "90"}

    monkeypatch.setattr(notifications.requests, "post", lambda *_args, **_kwargs: RateLimited())
    with pytest.raises(RetryableError) as rate_limit:
        notifications.notify("repair complete")
    assert rate_limit.value.retry_after == 30

    def timeout(*_args, **_kwargs):
        raise requests.Timeout("private URL details are not logged")

    monkeypatch.setattr(notifications.requests, "post", timeout)
    with pytest.raises(RetryableError):
        notifications.notify("repair complete")


@pytest.mark.base
def test_f14_rate_limit_and_timeout_resume_notification_without_repair_repeat(monkeypatch, tmp_path):
    path = configure_ledger(monkeypatch, tmp_path)
    monkeypatch.setenv("NOTIFY_PROVIDER", "telegram")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:abcdefghijklmnopqrstuvwxyz")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100123456")
    repairs = []
    responses = []

    class RateLimited:
        status_code = 429
        headers = {"Retry-After": "3"}

    class Accepted:
        status_code = 200
        headers = {}

        def json(self):
            return {"ok": True}

    sequence = [RateLimited(), requests.Timeout("private request details"), Accepted()]

    def send(*_args, **_kwargs):
        response = sequence.pop(0)
        responses.append(type(response).__name__)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(remediation, "repair", lambda *_args: repairs.append(True) or "repaired")
    monkeypatch.setattr(notifications.requests, "post", send)
    for _ in range(2):
        with pytest.raises(RetryableError):
            remediation.handle(event())
    remediation.handle(event())

    record = load(str(path))["evt-node-001"]
    assert record["repair_done"] is True and record["notified"] is True
    assert repairs == [True]
    assert responses == ["RateLimited", "Timeout", "Accepted"]
