"""Offline HMAC and FastAPI request-boundary tests."""

import asyncio
import time

import httpx
import pytest
from botocore.exceptions import ClientError

from fenix.services import receiver
from fenix.utils.crypto import signature, verify
from fenix.utils.errors import ValidationError


SECRET = "test-secret-long-enough-for-hmac"


def valid_inventory() -> dict:
    return {
        "node-01": {
            "type": "ec2",
            "group_id": "grupo-01",
            "instance_id": "i-test-001",
            "security_group_id": "sg-test-001",
            "expected_tags": {
                "ManagedBy": "ppa2",
                "Project": "fenix",
                "GroupId": "grupo-01",
                "Owner": "grupo-01",
                "Name": "fenix-grupo-01-node",
            },
            "status": "ready",
        }
    }


def signed_header(body: bytes, timestamp: int | None = None) -> str:
    timestamp = int(time.time()) if timestamp is None else timestamp
    return f"t={timestamp},v1={signature(SECRET, timestamp, body)}"


def post(body: bytes, headers=None):
    async def request():
        transport = httpx.ASGITransport(app=receiver.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/webhook", content=body, headers=headers or {})

    return asyncio.run(request())


def configure_receiver(monkeypatch, published=None):
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("QUEUE_PREFIX", "fenix-grupo-01")
    monkeypatch.setattr(receiver, "load", lambda _path: valid_inventory())
    monkeypatch.setattr(receiver, "queue_url", lambda _prefix: "local-queue-url")
    monkeypatch.setattr(
        receiver,
        "publish",
        lambda _url, event: (published.append(event) or "message-001") if published is not None else "message-001",
    )


@pytest.mark.base
def test_signature_authenticates_raw_bytes_and_rejects_ambiguous_headers():
    body = b'{"x":1}'
    header = signed_header(body, timestamp=1000)
    verify(SECRET, header, body, now=1000)
    with pytest.raises(ValidationError):
        verify(SECRET, header, b'{"x": 1}', now=1000)
    with pytest.raises(ValidationError):
        verify(SECRET, header + ",t=1000", body, now=1000)
    with pytest.raises(ValidationError):
        verify(SECRET, header, body, now=1301)


@pytest.mark.base
@pytest.mark.parametrize(
    "header_mode",
    ["missing", "malformed", "wrong", "stale"],
)
def test_signature_failures_return_401_without_publishing(monkeypatch, header_mode):
    published = []
    configure_receiver(monkeypatch, published)
    body = b'{"schema_version":1}'
    if header_mode == "missing":
        headers = {}
    elif header_mode == "malformed":
        headers = {"X-Webhook-Signature": "v1=not-a-signature"}
    elif header_mode == "wrong":
        valid = signed_header(body)
        wrong = "1" if valid[-1] == "0" else "0"
        headers = {"X-Webhook-Signature": valid[:-1] + wrong}
    else:
        old = int(time.time()) - 301
        headers = {"X-Webhook-Signature": signed_header(body, old)}
    response = post(body, headers)
    assert response.status_code == 401
    assert published == []


@pytest.mark.base
def test_duplicate_signature_headers_return_401(monkeypatch):
    published = []
    configure_receiver(monkeypatch, published)
    body = b"{}"
    signed = signed_header(body)
    response = post(
        body,
        [("X-Webhook-Signature", signed), ("X-Webhook-Signature", signed)],
    )
    assert response.status_code == 401
    assert published == []


@pytest.mark.base
def test_signed_invalid_json_is_400_and_signed_list_is_422(monkeypatch):
    published = []
    configure_receiver(monkeypatch, published)
    invalid_json = b"{bad"
    response = post(invalid_json, {"X-Webhook-Signature": signed_header(invalid_json)})
    assert response.status_code == 400

    array = b"[]"
    response = post(array, {"X-Webhook-Signature": signed_header(array)})
    assert response.status_code == 422
    assert published == []


@pytest.mark.base
def test_valid_signed_event_returns_202_only_after_publish_confirmation(monkeypatch):
    published = []
    configure_receiver(monkeypatch, published)
    body = (
        b'{"schema_version":1,"event_id":"evt-node-001","event_type":"instance.stopped",'
        b'"resource_id":"node-01","occurred_at":"2026-10-22T18:00:00Z","simulate_failures":0}'
    )
    response = post(body, {"X-Webhook-Signature": signed_header(body)})
    assert response.status_code == 202
    assert response.json() == {
        "status": "accepted",
        "event_id": "evt-node-001",
        "message_id": "message-001",
    }
    assert published[0]["event_id"] == "evt-node-001"


@pytest.mark.base
def test_invalid_utf8_duplicate_keys_and_oversized_body_are_rejected(monkeypatch):
    published = []
    configure_receiver(monkeypatch, published)
    invalid_utf8 = b"\xff"
    assert post(
        invalid_utf8,
        {"X-Webhook-Signature": signed_header(invalid_utf8)},
    ).status_code == 400
    duplicate = b'{"schema_version":1,"schema_version":1}'
    assert post(duplicate, {"X-Webhook-Signature": signed_header(duplicate)}).status_code == 400
    assert post(b"x" * 16_385).status_code == 413
    assert published == []


@pytest.mark.base
@pytest.mark.parametrize(
    "event",
    [
        b'{"schema_version":1,"event_id":"evt-001","event_type":"instance.stopped","resource_id":"arbitrary","occurred_at":"2026-10-22T18:00:00Z","simulate_failures":0}',
        b'{"schema_version":1,"event_id":"evt-001","event_type":"instance.stopped","resource_id":"node-01","occurred_at":"2026-10-22T18:00:00Z","simulate_failures":0,"extra":true}',
    ],
)
def test_bad_alias_and_extra_event_fields_return_422_without_publish(monkeypatch, event):
    published = []
    configure_receiver(monkeypatch, published)
    response = post(event, {"X-Webhook-Signature": signed_header(event)})
    assert response.status_code == 422
    assert published == []


@pytest.mark.base
def test_sqs_failure_returns_503_without_false_acceptance(monkeypatch):
    configure_receiver(monkeypatch)

    def unavailable(_url, _event):
        raise ClientError(
            {"Error": {"Code": "ServiceUnavailable", "Message": "not exposed"}},
            "SendMessage",
        )

    monkeypatch.setattr(receiver, "publish", unavailable)
    body = (
        b'{"schema_version":1,"event_id":"evt-node-001","event_type":"instance.stopped",'
        b'"resource_id":"node-01","occurred_at":"2026-10-22T18:00:00Z","simulate_failures":0}'
    )
    response = post(body, {"X-Webhook-Signature": signed_header(body)})
    assert response.status_code == 503
