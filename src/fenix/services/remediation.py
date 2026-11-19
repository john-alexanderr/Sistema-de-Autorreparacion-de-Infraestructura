"""Convergent resource repairs and the durable per-event processing ledger."""

import json

from botocore.exceptions import BotoCoreError, ClientError

from fenix.config.settings import client
from fenix.services.events import validate
from fenix.services.notifications import notify
from fenix.utils.errors import PermanentError, RetryableError, ValidationError
from fenix.utils.state import load, save


INVENTORY_PATH = "data/inventory.json"
EVENTS_PATH = "data/events.json"
_TRANSIENT_CODES = {
    "InternalError",
    "InternalFailure",
    "RequestLimitExceeded",
    "RequestTimeout",
    "RequestTimeoutException",
    "ServiceUnavailable",
    "SlowDown",
    "Throttling",
    "ThrottlingException",
}


def _aws_call(service: str, operation: str, **kwargs):
    try:
        return getattr(client(service), operation)(**kwargs)
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code")
        status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
        if code in _TRANSIENT_CODES or (isinstance(status, int) and status >= 500):
            raise RetryableError("Temporary local cloud API failure") from error
        raise PermanentError("Local cloud API rejected the authorized resource operation") from error
    except BotoCoreError as error:
        raise RetryableError("Local cloud API is temporarily unavailable") from error


def _tag_map(tags: list[dict]) -> dict[str, str]:
    result = {}
    for tag in tags:
        key, value = tag.get("Key"), tag.get("Value")
        if not isinstance(key, str) or not isinstance(value, str) or key in result:
            raise PermanentError("Cloud resource has invalid or duplicate tags")
        result[key] = value
    return result


def _verify_owner(actual: dict[str, str], expected: dict[str, str], allow_missing_owner: bool = False) -> None:
    for key in ("ManagedBy", "Project", "GroupId"):
        if actual.get(key) != expected.get(key):
            raise PermanentError("Cloud resource ownership could not be verified")
    owner = actual.get("Owner")
    if owner is not None and owner != expected.get("Owner"):
        raise PermanentError("Cloud resource belongs to another group")
    if owner is None and not allow_missing_owner:
        raise PermanentError("Cloud resource ownership could not be verified")


def _instance(resource: dict) -> tuple[dict, dict]:
    instance_id = resource.get("instance_id")
    expected_tags = resource.get("expected_tags")
    if not isinstance(instance_id, str) or not instance_id or not isinstance(expected_tags, dict):
        raise PermanentError("EC2 inventory record is incomplete")
    response = _aws_call("ec2", "describe_instances", InstanceIds=[instance_id])
    instances = [
        instance
        for reservation in response.get("Reservations", [])
        for instance in reservation.get("Instances", [])
    ]
    if len(instances) != 1:
        raise PermanentError("Authorized EC2 instance was not found")
    observed_tags = _tag_map(instances[0].get("Tags", []))
    if any(observed_tags.get(key) != value for key, value in expected_tags.items()):
        raise PermanentError("EC2 ownership or expected tags do not match inventory")
    return instances[0], expected_tags


def _repair_instance(resource: dict) -> str:
    instance, _ = _instance(resource)
    state = instance.get("State", {}).get("Name")
    if state == "running":
        return "already_ok"
    if state == "pending":
        raise RetryableError("EC2 instance is still starting")
    if state != "stopped":
        raise PermanentError("EC2 instance is not in a repairable state")
    instance_id = resource["instance_id"]
    _aws_call("ec2", "start_instances", InstanceIds=[instance_id])
    observed, _ = _instance(resource)
    state = observed.get("State", {}).get("Name")
    if state == "running":
        return "repaired"
    if state in {"pending", "stopped"}:
        raise RetryableError("EC2 start has not reached running state")
    raise PermanentError("EC2 instance entered an unexpected state during repair")


def _bucket_tags(s3, bucket_name: str) -> dict[str, str]:
    try:
        response = s3.get_bucket_tagging(Bucket=bucket_name)
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code")
        if code == "NoSuchTagSet":
            return {}
        status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
        if code in _TRANSIENT_CODES or (isinstance(status, int) and status >= 500):
            raise RetryableError("Temporary local cloud API failure") from error
        raise PermanentError("S3 could not verify the authorized bucket") from error
    except BotoCoreError as error:
        raise RetryableError("Local cloud API is temporarily unavailable") from error
    return _tag_map(response.get("TagSet", []))


def _repair_bucket(resource: dict) -> str:
    bucket_name = resource.get("bucket_name")
    expected = resource.get("expected_tags")
    if not isinstance(bucket_name, str) or not bucket_name or not isinstance(expected, dict):
        raise PermanentError("S3 inventory record is incomplete")
    s3 = client("s3")
    current = _bucket_tags(s3, bucket_name)
    _verify_owner(current, expected, allow_missing_owner=True)
    for key, value in expected.items():
        if key in {"ManagedBy", "Project", "GroupId", "Owner"}:
            continue
        if key in current and current[key] != value:
            raise PermanentError("Bucket expected tags conflict with inventory")
    merged = {**current, **expected}
    if len(merged) > 50:
        raise PermanentError("Bucket tag limit would be exceeded")
    changed = merged != current
    if changed:
        _aws_call(
            "s3",
            "put_bucket_tagging",
            Bucket=bucket_name,
            Tagging={"TagSet": [{"Key": key, "Value": value} for key, value in sorted(merged.items())]},
        )
    verified = _bucket_tags(s3, bucket_name)
    if any(verified.get(key) != value for key, value in expected.items()):
        raise RetryableError("S3 bucket tags have not converged yet")
    return "repaired" if changed else "already_ok"


def repair(resource: dict, event_type: str) -> str:
    """Converge the authorized EC2 instance or S3 bucket and verify the result."""
    if not isinstance(resource, dict) or resource.get("status", "ready") != "ready":
        raise PermanentError("Resource inventory record is not ready")
    if event_type == "instance.stopped" and resource.get("type") == "ec2":
        return _repair_instance(resource)
    if event_type == "bucket.tags_missing" and resource.get("type") == "s3":
        return _repair_bucket(resource)
    raise PermanentError("Event type does not match the authorized resource")


def _canonical(event: dict) -> str:
    return json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _persist_failure(ledger: dict, event_id: str, entry: dict, status: str) -> None:
    entry["status"] = status
    ledger[event_id] = entry
    save(EVENTS_PATH, ledger)


def handle(event: dict) -> None:
    """Resume a validated event from its last durably completed stage."""
    inventory = load(INVENTORY_PATH)
    if not isinstance(inventory, dict):
        raise ValidationError("Resource inventory is unavailable")
    validated = validate(event, inventory)
    event_id = validated["event_id"]
    ledger = load(EVENTS_PATH)
    if not isinstance(ledger, dict):
        raise ValidationError("Event ledger is not a JSON object")

    content_key = _canonical(validated)
    entry = ledger.get(event_id)
    if entry is not None:
        if not isinstance(entry, dict) or not isinstance(entry.get("content"), dict):
            raise ValidationError("Event ledger entry is invalid")
        if _canonical(entry["content"]) != content_key:
            conflicts = entry.setdefault("conflicts", [])
            if not isinstance(conflicts, list):
                raise ValidationError("Event ledger conflict record is invalid")
            if all(_canonical(item) != content_key for item in conflicts if isinstance(item, dict)):
                conflicts.append(validated)
            entry["status"] = "conflict"
            save(EVENTS_PATH, ledger)
            raise PermanentError("event_id was reused with different content")
        required = {"attempts", "repair_done", "repair_result", "notified", "status"}
        if not required.issubset(entry):
            raise ValidationError("Event ledger entry is incomplete")
        if type(entry["attempts"]) is not int or entry["attempts"] < 0:
            raise ValidationError("Event ledger attempt count is invalid")
        if type(entry["repair_done"]) is not bool or type(entry["notified"]) is not bool:
            raise ValidationError("Event ledger stage flags are invalid")
        if entry["repair_done"] and not isinstance(entry["repair_result"], str):
            raise ValidationError("Event ledger repair result is invalid")
        if not entry["repair_done"] and entry["repair_result"] is not None:
            raise ValidationError("Event ledger has a result without a completed repair")
        if entry["notified"] and not entry["repair_done"]:
            raise ValidationError("Event ledger notification precedes repair")
        if entry["status"] not in {
            "pending",
            "processing",
            "retrying",
            "repair_complete",
            "failed",
            "conflict",
            "complete",
        }:
            raise ValidationError("Event ledger status is invalid")
        if not isinstance(entry.get("conflicts", []), list):
            raise ValidationError("Event ledger conflict record is invalid")
    else:
        entry = {
            "content": validated,
            "attempts": 0,
            "repair_done": False,
            "repair_result": None,
            "notified": False,
            "status": "pending",
            "conflicts": [],
        }
        ledger[event_id] = entry

    if entry["repair_done"] and entry["notified"]:
        return

    entry["attempts"] += 1
    entry["status"] = "processing"
    ledger[event_id] = entry
    save(EVENTS_PATH, ledger)

    if not entry["repair_done"] and entry["attempts"] <= validated["simulate_failures"]:
        _persist_failure(ledger, event_id, entry, "retrying")
        raise RetryableError("Configured transient event failure")

    resource = inventory[validated["resource_id"]]
    if not entry["repair_done"]:
        try:
            result = repair(resource, validated["event_type"])
        except RetryableError:
            _persist_failure(ledger, event_id, entry, "retrying")
            raise
        except (PermanentError, ValidationError):
            _persist_failure(ledger, event_id, entry, "failed")
            raise
        entry["repair_done"] = True
        entry["repair_result"] = result
        entry["status"] = "repair_complete"
        ledger[event_id] = entry
        save(EVENTS_PATH, ledger)

    if not entry["notified"]:
        text = (
            f"Fenix event {event_id}: {validated['event_type']} on "
            f"{validated['resource_id']} ({entry['repair_result']})"
        )
        try:
            notify(text[:1000])
        except RetryableError:
            _persist_failure(ledger, event_id, entry, "retrying")
            raise
        except PermanentError:
            _persist_failure(ledger, event_id, entry, "failed")
            raise
        entry["notified"] = True
    entry["status"] = "complete"
    ledger[event_id] = entry
    save(EVENTS_PATH, ledger)
