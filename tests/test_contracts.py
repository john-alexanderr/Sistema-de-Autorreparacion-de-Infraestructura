"""Pruebas unitarias sin conexión de identificadores, marcas de tiempo y el contrato de eventos."""

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
            "id": "i-test-001",
            "security_group_id": "sg-test-001",
            "expected_tags": {**ownership, "Name": "fenix-grupo-01-node"},
            "status": "ready",
        },
        "bucket-01": {
            "type": "s3",
            "group_id": "grupo-01",
            "id": "fenix-grupo-01-demo",
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
def test_event_contract_requires_canonical_inventory_id_key():
    allowed = inventory()
    bucket_event = event(
        event_id="evt-bucket-001",
        event_type="bucket.tags_missing",
        resource_id="bucket-01",
    )
    assert validate(event(), allowed)["resource_id"] == "node-01"
    assert validate(bucket_event, allowed)["resource_id"] == "bucket-01"

    for alias, obsolete_key, target_event in (
        ("node-01", "instance_id", event()),
        ("bucket-01", "bucket_name", bucket_event),
    ):
        resource = allowed[alias]
        resource[obsolete_key] = resource.pop("id")
        with pytest.raises(ValidationError):
            validate(target_event, allowed)


@pytest.mark.base
def test_cloud_client_fails_closed_and_uses_dummy_local_credentials(monkeypatch):
    monkeypatch.setattr(settings, "load_dotenv", lambda: None)
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://127.0.0.1:4566")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
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


@pytest.mark.base
@pytest.mark.parametrize("missing_variable", ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"))
def test_cloud_client_requires_both_credentials_before_calling_boto3(monkeypatch, missing_variable):
    monkeypatch.setattr(settings, "load_dotenv", lambda: None)
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://127.0.0.1:4566")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "dummy-local-access-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "dummy-local-secret-key")
    monkeypatch.delenv(missing_variable)
    calls = []
    monkeypatch.setattr(settings.boto3, "client", lambda *args, **kwargs: calls.append((args, kwargs)))

    with pytest.raises(ValidationError, match=f"Missing {missing_variable}"):
        settings.client("sqs")

    assert calls == []


@pytest.mark.base
@pytest.mark.parametrize(
    ("access_key_id", "secret_access_key"),
    (("unsafe-access-key", "test"), ("test", "unsafe-secret-value")),
)
def test_cloud_client_rejects_non_test_credentials_before_calling_boto3(
    monkeypatch, access_key_id, secret_access_key
):
    monkeypatch.setattr(settings, "load_dotenv", lambda: None)
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://127.0.0.1:4566")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", access_key_id)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", secret_access_key)
    calls = []
    monkeypatch.setattr(settings.boto3, "client", lambda *args, **kwargs: calls.append((args, kwargs)))

    with pytest.raises(ValidationError) as error:
        settings.client("sqs")

    assert access_key_id not in str(error.value)
    assert secret_access_key not in str(error.value)
    assert calls == []
