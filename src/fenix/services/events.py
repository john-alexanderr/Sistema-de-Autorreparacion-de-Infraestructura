"""Closed event contract and inventory alias resolution."""

from fenix.utils.errors import ValidationError
from fenix.utils.validation import identifier, utc_text


EVENT_FIELDS = {
    "schema_version",
    "event_id",
    "event_type",
    "resource_id",
    "occurred_at",
    "simulate_failures",
}
EVENT_RESOURCE_TYPES = {
    "instance.stopped": ("node-01", "ec2"),
    "bucket.tags_missing": ("bucket-01", "s3"),
}
OWNERSHIP_TAGS = {"ManagedBy": "ppa2", "Project": "fenix"}


def validate(event: dict, inventory: dict) -> dict:
    """Validate the closed JSON schema and resolve an authorized alias."""
    if not isinstance(event, dict):
        raise ValidationError("Event must be a JSON object")
    if set(event) != EVENT_FIELDS:
        raise ValidationError("Event contains missing or unsupported fields")
    if type(event["schema_version"]) is not int or event["schema_version"] != 1:
        raise ValidationError("Unsupported event schema version")
    identifier(event["event_id"])
    identifier(event["resource_id"])
    if not isinstance(event["occurred_at"], str):
        raise ValidationError("Event timestamp must be a string")
    utc_text(event["occurred_at"])
    failures = event["simulate_failures"]
    if type(failures) is not int or not 0 <= failures <= 5:
        raise ValidationError("simulate_failures must be an integer from 0 to 5")

    event_type = event["event_type"]
    mapping = EVENT_RESOURCE_TYPES.get(event_type) if isinstance(event_type, str) else None
    if mapping is None:
        raise ValidationError("Unsupported event type")
    expected_alias, expected_resource_type = mapping
    alias = event["resource_id"]
    if alias != expected_alias:
        raise ValidationError("Event type does not authorize this resource alias")
    if not isinstance(inventory, dict):
        raise ValidationError("Resource inventory is unavailable")
    resource = inventory.get(alias)
    if not isinstance(resource, dict) or resource.get("type") != expected_resource_type:
        raise ValidationError("Resource alias is not present in the authorized inventory")
    if resource.get("status", "ready") != "ready":
        raise ValidationError("Resource setup is incomplete")

    group_id = resource.get("group_id")
    identifier(group_id)
    expected_tags = resource.get("expected_tags")
    if not isinstance(expected_tags, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in expected_tags.items()
    ):
        raise ValidationError("Inventory expected_tags must be a string map")
    required_tags = {**OWNERSHIP_TAGS, "GroupId": group_id, "Owner": group_id}
    if any(expected_tags.get(key) != value for key, value in required_tags.items()):
        raise ValidationError("Inventory ownership tags are inconsistent")

    if expected_resource_type == "ec2":
        for key in ("id", "security_group_id"):
            if not isinstance(resource.get(key), str) or not resource[key]:
                raise ValidationError("EC2 inventory record is incomplete")
    elif not isinstance(resource.get("id"), str) or not resource["id"]:
        raise ValidationError("S3 inventory record is incomplete")

    return dict(event)
