"""Read-only inspection of the group's inventory, S3, EC2, and security groups.

The script compares ``data/inventory.json`` with the LocalStack resources that
carry the required ownership tags. It never creates, updates, or deletes any
resource. Run it from the repository root::

    ./.venv/bin/python scripts/inspect_resources.py
    ./.venv/bin/python scripts/inspect_resources.py --group GROUP_ID --json
"""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv

from fenix.config.settings import client
from fenix.utils.errors import ValidationError
from fenix.utils.state import load
from fenix.utils.validation import identifier


OWNERSHIP_KEYS = ("ManagedBy", "Project", "GroupId", "Owner")
_RESOURCE_ID_PLACEHOLDER = "<RESOURCE_ID>"
_PRIVATE_IP_PLACEHOLDER = "<PRIVATE_IP>"
_TAG_VALUE_PLACEHOLDER = "<TAG_VALUE>"
_REDACTED_PATH_PLACEHOLDER = "<REDACTED_PATH>"
_NOT_FOUND_CODES = {
    "404",
    "NoSuchBucket",
    "NotFound",
    "InvalidInstanceID.NotFound",
}
_ACCESS_DENIED_CODES = {"403", "AccessDenied"}
_NO_TAG_SET_CODES = {"NoSuchTagSet", "NoSuchTagSetError"}


def _required_ownership(group: str) -> dict[str, str]:
    """Return the four ownership tags every group resource must carry."""
    return {
        "ManagedBy": "ppa2",
        "Project": "fenix",
        "GroupId": group,
        "Owner": group,
    }


def _tags_dict(raw: object) -> dict[str, str]:
    """Convert an AWS tag list to a plain dictionary without trusting values."""
    tags = {}
    if not isinstance(raw, list):
        return tags
    for tag in raw:
        if not isinstance(tag, dict):
            continue
        key = tag.get("Key")
        value = tag.get("Value")
        if isinstance(key, str) and isinstance(value, str):
            tags[key] = value
    return tags


def _safe_tags(tags: dict[str, str]) -> dict[str, str]:
    """Keep tag-key evidence while redacting every potentially identifying value."""
    return {key: _TAG_VALUE_PLACEHOLDER for key in sorted(tags)}


def _ownership_ok(tags: dict[str, str], group: str) -> bool:
    """Check that all required ownership tags match the observed tags."""
    required = _required_ownership(group)
    return all(tags.get(key) == value for key, value in required.items())


def _error_code(error: ClientError) -> object:
    """Return the AWS error code or HTTP status from a ClientError."""
    code = error.response.get("Error", {}).get("Code")
    status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code if code is not None else status


def _describe_error(error: Exception) -> str:
    """Return an error class without potentially identifying provider details."""
    return type(error).__name__


def _display_inventory_path(path: Path) -> str:
    """Show repo-relative paths and conceal caller-supplied external paths."""
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return _REDACTED_PATH_PLACEHOLDER


def _inventory_entries(inventory: dict) -> list[dict]:
    """Read every dictionary alias from the inventory."""
    entries = []
    for alias, record in inventory.items():
        if not isinstance(record, dict):
            continue
        expected_tags = record.get("expected_tags")
        entries.append(
            {
                "alias": alias,
                "id": record.get("id"),
                "type": record.get("type"),
                "group_id": record.get("group_id"),
                "expected_tags": expected_tags if isinstance(expected_tags, dict) else {},
                "security_group_id": record.get("security_group_id"),
            }
        )
    return entries


def _inspect_bucket(
    s3,
    name: str,
    inventory_ids: set[str],
    group: str,
) -> dict:
    """Inspect one bucket with read-only head and tagging calls."""
    exists = False
    tags: dict[str, str] = {}
    head_error = None
    try:
        s3.head_bucket(Bucket=name)
        exists = True
    except ClientError as error:
        code = _error_code(error)
        status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if status == 404 or code in _NOT_FOUND_CODES:
            exists = False
        elif status == 403 or code in _ACCESS_DENIED_CODES:
            exists = True
            head_error = "head_bucket: access denied"
        else:
            raise
    if exists and head_error is None:
        try:
            response = s3.get_bucket_tagging(Bucket=name)
            tags = _tags_dict(response.get("TagSet", []))
        except ClientError as error:
            code = _error_code(error)
            if code not in _NO_TAG_SET_CODES:
                raise
    return {
        "name": name,
        "exists": exists,
        "tags": _safe_tags(tags),
        "ownership_ok": exists and _ownership_ok(tags, group),
        "in_inventory": name in inventory_ids,
        "error": head_error,
    }


def _instance_record(
    instance: dict,
    inventory_ids: set[str],
    group: str,
) -> dict:
    """Build a read-only EC2 instance record from a describe response."""
    tags = _tags_dict(instance.get("Tags", []))
    security_group_ids = sorted(
        security_group.get("GroupId")
        for security_group in instance.get("SecurityGroups", [])
        if isinstance(security_group, dict)
        and isinstance(security_group.get("GroupId"), str)
    )
    return {
        "id": instance.get("InstanceId"),
        "state": instance.get("State", {}).get("Name"),
        "type": instance.get("InstanceType"),
        "private_ip": instance.get("PrivateIpAddress"),
        "tags": _safe_tags(tags),
        "security_group_ids": security_group_ids,
        "ownership_ok": _ownership_ok(tags, group),
        "in_inventory": instance.get("InstanceId") in inventory_ids,
    }


def _reservation_instances(response: dict) -> list[dict]:
    """Flatten the EC2 reservation structure into instance dictionaries."""
    instances = []
    for reservation in response.get("Reservations", []):
        if not isinstance(reservation, dict):
            continue
        for instance in reservation.get("Instances", []):
            if isinstance(instance, dict):
                instances.append(instance)
    return instances


def _inspect_instances(
    ec2,
    group: str,
    inventory_ids: list[str],
) -> tuple[dict[str, dict], list[str]]:
    """Inspect owned instances plus inventory IDs that must exist."""
    required = _required_ownership(group)
    filters = [
        {"Name": f"tag:{key}", "Values": [value]}
        for key, value in required.items()
    ]
    records: dict[str, dict] = {}
    for instance in _reservation_instances(ec2.describe_instances(Filters=filters)):
        record = _instance_record(instance, set(inventory_ids), group)
        instance_id = record["id"]
        if isinstance(instance_id, str) and instance_id:
            records[instance_id] = record
    missing = []
    for instance_id in inventory_ids:
        if instance_id in records:
            continue
        try:
            response = ec2.describe_instances(InstanceIds=[instance_id])
        except ClientError as error:
            if _error_code(error) == "InvalidInstanceID.NotFound":
                missing.append(instance_id)
                continue
            raise
        found = _reservation_instances(response)
        if not found:
            missing.append(instance_id)
            continue
        for instance in found:
            record = _instance_record(instance, set(inventory_ids), group)
            if record["id"] == instance_id:
                records[instance_id] = record
    return records, missing


def _inspect_security_groups(ec2, group: str) -> list[dict]:
    """Inspect the group security groups by name and ownership tags."""
    required = _required_ownership(group)
    filters = [
        {"Name": "group-name", "Values": [f"fenix-{group}-sg"]},
        *[
            {"Name": f"tag:{key}", "Values": [value]}
            for key, value in required.items()
        ],
    ]
    groups = ec2.describe_security_groups(Filters=filters).get("SecurityGroups", [])
    records = []
    for group_record in groups:
        if not isinstance(group_record, dict):
            continue
        tags = _tags_dict(group_record.get("Tags", []))
        records.append(
            {
                "id": group_record.get("GroupId"),
                "name": group_record.get("GroupName"),
                "vpc_id": group_record.get("VpcId"),
                "tags": _safe_tags(tags),
                "ownership_ok": _ownership_ok(tags, group),
            }
        )
    return records


def _expected_failures(
    entries: list[dict],
    s3_records: list[dict],
    ec2_records: dict,
    security_groups: list[dict],
) -> list[str]:
    """List inventory resources that are missing or do not carry ownership tags."""
    s3_by_name = {record["name"]: record for record in s3_records}
    security_group_ids = {record["id"] for record in security_groups}
    failures = []
    for entry in entries:
        entry_type = entry["type"]
        entry_id = entry["id"]
        if not isinstance(entry_id, str) or not entry_id:
            continue
        if entry_type == "s3":
            record = s3_by_name.get(entry_id)
            if record is None or not record["exists"]:
                failures.append("An expected S3 bucket is missing")
            elif not record["ownership_ok"]:
                failures.append("An expected S3 bucket lacks required ownership tags")
        elif entry_type == "ec2":
            record = ec2_records.get(entry_id)
            if record is None:
                failures.append("An expected EC2 instance is missing")
                continue
            if not record["ownership_ok"]:
                failures.append("An expected EC2 instance lacks required ownership tags")
            expected_sg_id = entry.get("security_group_id")
            if isinstance(expected_sg_id, str) and expected_sg_id:
                if expected_sg_id not in record["security_group_ids"]:
                    failures.append(
                        "An expected EC2 instance is not attached to its "
                        "expected security group"
                    )
                elif expected_sg_id not in security_group_ids:
                    failures.append(
                        "An expected security group is missing or lacks "
                        "required ownership tags"
                    )
    return failures


def _summary(s3_records: list[dict], ec2_records: dict, missing_ec2: list[str]) -> dict:
    """Build the owned/foreign/missing counters."""
    return {
        "ec2": {
            "owned": sum(1 for record in ec2_records.values() if record["ownership_ok"]),
            "foreign": sum(
                1 for record in ec2_records.values() if not record["ownership_ok"]
            ),
            "missing": len(missing_ec2),
        },
        "s3": {
            "owned": sum(1 for record in s3_records if record["ownership_ok"]),
            "foreign": sum(
                1
                for record in s3_records
                if record["exists"] and not record["ownership_ok"]
            ),
            "missing": sum(1 for record in s3_records if not record["exists"]),
        },
    }


def _public_bucket_record(record: dict) -> dict:
    """Return a bucket record with identifiers and tag values removed."""
    return {
        "name": _RESOURCE_ID_PLACEHOLDER,
        "exists": record["exists"],
        "tags": _safe_tags(record["tags"]),
        "ownership_ok": record["ownership_ok"],
        "in_inventory": record["in_inventory"],
        "error": record["error"],
    }


def _public_instance_record(record: dict) -> dict:
    """Return an instance record with identifiers and network data removed."""
    return {
        "id": _RESOURCE_ID_PLACEHOLDER,
        "state": record["state"],
        "type": record["type"],
        "private_ip": (
            _PRIVATE_IP_PLACEHOLDER if record.get("private_ip") else None
        ),
        "tags": _safe_tags(record["tags"]),
        "security_group_count": len(record["security_group_ids"]),
        "ownership_ok": record["ownership_ok"],
        "in_inventory": record["in_inventory"],
    }


def _public_security_group_record(record: dict) -> dict:
    """Return a security-group record without resource or tag values."""
    return {
        "id": _RESOURCE_ID_PLACEHOLDER,
        "name": _RESOURCE_ID_PLACEHOLDER,
        "vpc_id": _RESOURCE_ID_PLACEHOLDER if record.get("vpc_id") else None,
        "tags": _safe_tags(record["tags"]),
        "ownership_ok": record["ownership_ok"],
    }


def _print_human(result: dict) -> None:
    """Render the inspection report for a human reader."""
    print(f"Inventory: {result['inventory_path']}")
    print(f"Group: {result['group']}")
    print(f"Inventory aliases: {result['inventory_alias_count']}")
    print()
    print("S3 buckets:")
    if not result["s3"]:
        print("  (none)")
    for bucket in result["s3"]:
        print(
            f"  - {bucket['name']}: exists={bucket['exists']} "
            f"in_inventory={bucket['in_inventory']} "
            f"ownership_ok={bucket['ownership_ok']} tags={bucket['tags']}"
        )
        if bucket["error"]:
            print(f"    note: {bucket['error']}")
    print()
    print("EC2 instances:")
    if not result["ec2"]:
        print("  (none)")
    for instance in result["ec2"]:
        print(
            f"  - {instance['id']}: state={instance['state']} "
            f"type={instance['type']} private_ip={instance['private_ip']} "
            f"in_inventory={instance['in_inventory']} "
            f"ownership_ok={instance['ownership_ok']} "
            f"security_group_count={instance['security_group_count']} "
            f"tags={instance['tags']}"
        )
    if result["missing_ec2"]:
        print(f"  missing inventory resources: {result['missing_ec2']}")
    print()
    print("Security groups:")
    if not result["security_groups"]:
        print("  (none)")
    for security_group in result["security_groups"]:
        print(
            f"  - {security_group['id']} ({security_group['name']}): "
            f"vpc={security_group['vpc_id']} "
            f"ownership_ok={security_group['ownership_ok']} "
            f"tags={security_group['tags']}"
        )
    print()
    summary = result["summary"]
    print("Summary:")
    print(
        "  EC2: "
        f"owned={summary['ec2']['owned']} foreign={summary['ec2']['foreign']} "
        f"missing={summary['ec2']['missing']}"
    )
    print(
        "  S3: "
        f"owned={summary['s3']['owned']} foreign={summary['s3']['foreign']} "
        f"missing={summary['s3']['missing']}"
    )
    print(f"  Verdict: {'OK' if result['ok'] else 'FAILED'}")
    for failure in result["failures"]:
        print(f"  - {failure}")


def _build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser after .env values are available for defaults."""
    parser = argparse.ArgumentParser(
        description="Inspect the group's inventory and cloud resources without mutating them.",
    )
    parser.add_argument(
        "--group",
        default=os.getenv("GROUP_ID"),
        help="Group identifier (default: GROUP_ID from .env).",
    )
    parser.add_argument(
        "--inventory",
        default="data/inventory.json",
        help="Inventory path, relative to the repository root by default.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print only the JSON report on stdout.",
    )
    return parser


def main(argv=None) -> int:
    """Run the read-only resource inspection and return a process exit code."""
    load_dotenv(ROOT / ".env")
    parser = _build_parser()
    args = parser.parse_args(argv)
    group = args.group
    if not group:
        print(
            "Missing configuration: GROUP_ID is not set. "
            "Set it in .env or pass --group.",
            file=sys.stderr,
        )
        return 2
    try:
        identifier(group)
    except ValidationError:
        print("Missing configuration: GROUP_ID is invalid.", file=sys.stderr)
        return 2
    inventory_path = Path(args.inventory)
    if not inventory_path.is_absolute():
        inventory_path = ROOT / inventory_path
    try:
        inventory_path = inventory_path.resolve()
    except (OSError, RuntimeError):
        print(
            f"Inventory error: cannot resolve {_REDACTED_PATH_PLACEHOLDER}.",
            file=sys.stderr,
        )
        return 1
    display_path = _display_inventory_path(inventory_path)
    try:
        inventory = load(str(inventory_path))
    except (OSError, ValueError):
        print(
            f"Inventory error: cannot read {display_path}.",
            file=sys.stderr,
        )
        return 1
    if not isinstance(inventory, dict) or not inventory:
        print(
            f"Inventory error: {display_path} is missing or empty.",
            file=sys.stderr,
        )
        return 1
    entries = _inventory_entries(inventory)
    try:
        s3 = client("s3")
        ec2 = client("ec2")
    except ValidationError:
        print(
            "Missing configuration: cloud client settings are invalid.",
            file=sys.stderr,
        )
        return 2
    try:
        inventory_s3_ids = [
            entry["id"]
            for entry in entries
            if entry["type"] == "s3" and isinstance(entry["id"], str) and entry["id"]
        ]
        inventory_ec2_ids = [
            entry["id"]
            for entry in entries
            if entry["type"] == "ec2" and isinstance(entry["id"], str) and entry["id"]
        ]
        demo_bucket = f"fenix-{group}-demo"
        bucket_names = list(dict.fromkeys([*inventory_s3_ids, demo_bucket]))
        s3_records = [
            _inspect_bucket(s3, name, set(inventory_s3_ids), group)
            for name in bucket_names
        ]
        ec2_records, missing_ec2 = _inspect_instances(
            ec2, group, inventory_ec2_ids
        )
        security_groups = _inspect_security_groups(ec2, group)
    except (ClientError, BotoCoreError, ValidationError) as error:
        print(f"Operational error: {_describe_error(error)}", file=sys.stderr)
        return 1
    failures = _expected_failures(entries, s3_records, ec2_records, security_groups)
    if not inventory_s3_ids and not inventory_ec2_ids:
        failures.append("inventory has no S3 or EC2 resources to verify")
    result = {
        "group": _TAG_VALUE_PLACEHOLDER,
        "inventory_path": display_path,
        "inventory_alias_count": len(entries),
        "s3": [_public_bucket_record(record) for record in s3_records],
        "ec2": [
            _public_instance_record(record) for record in ec2_records.values()
        ],
        "missing_ec2": len(missing_ec2),
        "security_groups": [
            _public_security_group_record(record) for record in security_groups
        ],
        "summary": _summary(s3_records, ec2_records, missing_ec2),
        "ok": not failures,
        "failures": failures,
    }
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _print_human(result)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
