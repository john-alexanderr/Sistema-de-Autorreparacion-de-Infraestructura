"""Offline unit tests for identifiers, timestamps, and the event contract."""

import pytest

from fenix.services.events import validate
from fenix.config import settings
from fenix.utils.errors import ValidationError
from fenix.utils.validation import identifier, ttl_seconds, utc_text


def inventory() -> dict:
    ownership = {
        "ManagedBy": "ppa2",
        "Project": "fenix",
        "GroupId": "grupo-01",
        "Owner": "grupo-01",
    }
    return {
        "node-01": {
            "type": "ec2",
            "group_id": "grupo-01",
            "instance_id": "i-test-001",
            "security_group_id": "sg-test-001",
            "expected_tags": {**ownership, "Name": "fenix-grupo-01-node"},
            "status": "ready",
        },
        "bucket-01": {
            "type": "s3",
            "group_id": "grupo-01",
            "bucket_name": "fenix-grupo-01-demo",
            "expected_tags": ownership,
            "status": "ready",
        },
    }


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


@pytest.mark.base
def test_identifier_requires_the_exact_closed_format():
    assert identifier("grupo-01") == "grupo-01"
    for value in ("../group", "Grupo-01", "ab", "a" * 33, 123):
        with pytest.raises(ValidationError):
            identifier(value)


@pytest.mark.base
def test_ttl_is_decimal_and_bounded():
    assert ttl_seconds("60") == 60
    assert ttl_seconds("600") == 600
    for value in ("59", "601", "1.5", " 60", "+60", "true", 60):
        with pytest.raises(ValidationError):
            ttl_seconds(value)


@pytest.mark.base
def test_timestamp_requires_explicit_utc():
    assert utc_text("2026-10-22T18:00:00Z").utcoffset().total_seconds() == 0
    assert utc_text("2026-10-22T18:00:00+00:00").isoformat().endswith("+00:00")
    for value in (
        "2026-10-22T18:00:00",
        "2026-10-22T18:00:00+01:00",
        "2026-10-22T18:00:00-00:00",
        "2026-10-22 18:00:00Z",
        None,
    ):
        with pytest.raises(ValidationError):
            utc_text(value)


@pytest.mark.base
def test_event_contract_rejects_extra_fields_and_boolean_integers():
    allowed = inventory()
    assert validate(event(), allowed)["event_id"] == "evt-node-001"
    for invalid in (
        event(simulate_failures=True),
        event(schema_version=True),
        event(resource_id="i-123456"),
        event(extra="not allowed"),
        event(event_type="bucket.tags_missing", resource_id="node-01"),
    ):
        with pytest.raises(ValidationError):
            validate(invalid, allowed)


@pytest.mark.base
def test_event_contract_requires_ready_owned_inventory_alias():
    allowed = inventory()
    allowed["node-01"]["status"] = "provisioning"
    with pytest.raises(ValidationError):
        validate(event(), allowed)
    allowed["node-01"]["status"] = "ready"
    allowed["node-01"]["expected_tags"]["GroupId"] = "other-group"
    with pytest.raises(ValidationError):
        validate(event(), allowed)


@pytest.mark.base
def test_cloud_client_fails_closed_and_uses_dummy_local_credentials(monkeypatch):
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://127.0.0.1:4566")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    calls = []
    monkeypatch.setattr(settings.boto3, "client", lambda *args, **kwargs: calls.append((args, kwargs)) or "client")
    assert settings.client("sqs") == "client"
    assert calls[0][1]["aws_access_key_id"] == "test"
    assert calls[0][1]["aws_secret_access_key"] == "test"

    for endpoint in (
        "https://127.0.0.1:4566",
        "http://example.com:4566",
        "http://localhost:4567",
        "http://localhost:4566/path",
    ):
        monkeypatch.setenv("AWS_ENDPOINT_URL", endpoint)
        with pytest.raises(ValidationError):
            settings.client("sqs")
