"""Create and safely reconcile the group's LocalStack lab resources."""

import hashlib
import time

from botocore.exceptions import ClientError

from fenix.config.settings import client
from fenix.utils.errors import PermanentError, ValidationError
from fenix.utils.state import load, save
from fenix.utils.validation import identifier


INVENTORY_PATH = "data/inventory.json"
_OWNERSHIP_KEYS = ("ManagedBy", "Project", "GroupId", "Owner")


def _tags_dict(tags: list[dict]) -> dict[str, str]:
    result = {}
    for tag in tags:
        key, value = tag.get("Key"), tag.get("Value")
        if not isinstance(key, str) or not isinstance(value, str) or key in result:
            raise PermanentError("Cloud resource has invalid or duplicate tags")
        result[key] = value
    return result


def _tag_list(tags: dict[str, str]) -> list[dict[str, str]]:
    return [{"Key": key, "Value": value} for key, value in sorted(tags.items())]


def _require_tags(actual: dict[str, str], expected: dict[str, str]) -> None:
    if any(actual.get(key) != value for key, value in expected.items()):
        raise PermanentError("Cloud resource ownership tags do not match this group")


def _save_entry(inventory: dict, alias: str, record: dict) -> None:
    inventory[alias] = record
    save(INVENTORY_PATH, inventory)


def _group_inventory(group: str) -> dict:
    inventory = load(INVENTORY_PATH)
    if not isinstance(inventory, dict):
        raise ValidationError("Inventory must be a JSON object")
    for alias in ("node-01", "bucket-01"):
        existing = inventory.get(alias)
        if existing is not None and (
            not isinstance(existing, dict) or existing.get("group_id") != group
        ):
            raise ValidationError("Inventory belongs to another group; refusing to overwrite it")
    return inventory


def _find_security_group(ec2, group: str, vpc_id: str, tags: dict[str, str]) -> dict | None:
    filters = [
        {"Name": "vpc-id", "Values": [vpc_id]},
        {"Name": "group-name", "Values": [f"fenix-{group}-sg"]},
        *[
            {"Name": f"tag:{key}", "Values": [value]}
            for key, value in tags.items()
        ],
    ]
    groups = ec2.describe_security_groups(Filters=filters).get("SecurityGroups", [])
    if len(groups) > 1:
        raise PermanentError("Multiple matching security groups were found")
    return groups[0] if groups else None


def _find_instance(ec2, tags: dict[str, str]) -> dict | None:
    filters = [
        {"Name": f"tag:{key}", "Values": [value]}
        for key, value in tags.items()
    ]
    filters.append({"Name": "instance-state-name", "Values": ["pending", "running", "stopped"]})
    instances = [
        instance
        for reservation in ec2.describe_instances(Filters=filters).get("Reservations", [])
        for instance in reservation.get("Instances", [])
    ]
    if len(instances) > 1:
        raise PermanentError("Multiple matching EC2 instances were found")
    return instances[0] if instances else None


def _default_vpc(ec2) -> str:
    vpcs = ec2.describe_vpcs(
        Filters=[{"Name": "is-default", "Values": ["true"]}]
    ).get("Vpcs", [])
    if len(vpcs) != 1 or not isinstance(vpcs[0].get("VpcId"), str):
        raise PermanentError("A single default VPC is required for the lab")
    return vpcs[0]["VpcId"]


def _ensure_bucket(s3, inventory: dict, group: str, bucket_name: str, tags: dict[str, str]) -> None:
    previous = inventory.get("bucket-01", {})
    record = {
        "type": "s3",
        "group_id": group,
        "id": bucket_name,
        "expected_tags": tags,
        "status": "provisioning",
        "created_by_setup": bool(previous.get("created_by_setup")),
    }
    _save_entry(inventory, "bucket-01", record)

    created_now = False
    try:
        s3.create_bucket(Bucket=bucket_name)
        created_now = True
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code")
        if code not in {"BucketAlreadyExists", "BucketAlreadyOwnedByYou"}:
            raise

    if created_now:
        record["created_by_setup"] = True
        _save_entry(inventory, "bucket-01", record)

    try:
        current = _tags_dict(s3.get_bucket_tagging(Bucket=bucket_name).get("TagSet", []))
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code")
        if code != "NoSuchTagSet":
            raise
        current = {}

    required_ownership = {key: tags[key] for key in _OWNERSHIP_KEYS if key != "Owner"}
    if current:
        _require_tags(current, required_ownership)
        if current.get("Owner") not in (None, group):
            raise PermanentError("Bucket owner tag belongs to another group")
    elif not created_now and not record["created_by_setup"]:
        raise PermanentError("Unowned bucket already exists; refusing to modify it")

    merged = {**current, **tags}
    if len(merged) > 50:
        raise PermanentError("Bucket tag limit would be exceeded")
    if merged != current:
        s3.put_bucket_tagging(
            Bucket=bucket_name,
            Tagging={"TagSet": _tag_list(merged)},
        )
    verified = _tags_dict(s3.get_bucket_tagging(Bucket=bucket_name).get("TagSet", []))
    _require_tags(verified, tags)
    record["status"] = "ready"
    record.pop("created_by_setup", None)
    _save_entry(inventory, "bucket-01", record)


def setup_demo(group: str) -> dict:
    """Create or reconcile one tagged EC2 instance and one tagged S3 bucket."""
    identifier(group)
    inventory = _group_inventory(group)
    ec2 = client("ec2")
    s3 = client("s3")
    if getattr(s3.meta, "region_name", None) != "us-east-1":
        raise ValidationError("The LocalStack lab bucket must use us-east-1")
    vpc_id = _default_vpc(ec2)

    ownership = {
        "ManagedBy": "ppa2",
        "Project": "fenix",
        "GroupId": group,
        "Owner": group,
    }
    node_name = f"fenix-{group}-node"
    security_group_tags = {**ownership, "Name": f"fenix-{group}-sg"}
    node_tags = {**ownership, "Name": node_name}
    previous_node = inventory.get("node-01", {})
    saved_image_id = previous_node.get("image_id") if isinstance(previous_node, dict) else None

    security_group = _find_security_group(ec2, group, vpc_id, security_group_tags)
    if security_group is None:
        try:
            result = ec2.create_security_group(
                GroupName=f"fenix-{group}-sg",
                Description=f"Fenix lab security group for {group}",
                VpcId=vpc_id,
                TagSpecifications=[
                    {"ResourceType": "security-group", "Tags": _tag_list(security_group_tags)}
                ],
            )
            security_group_id = result["GroupId"]
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") != "InvalidGroup.Duplicate":
                raise
            security_group = _find_security_group(ec2, group, vpc_id, security_group_tags)
            if security_group is None:
                raise PermanentError("An unowned security group uses the expected name") from error
            security_group_id = security_group["GroupId"]
    else:
        _require_tags(_tags_dict(security_group.get("Tags", [])), security_group_tags)
        security_group_id = security_group["GroupId"]

    confirmed_groups = ec2.describe_security_groups(GroupIds=[security_group_id]).get("SecurityGroups", [])
    if len(confirmed_groups) != 1:
        raise PermanentError("Created security group could not be verified")
    _require_tags(_tags_dict(confirmed_groups[0].get("Tags", [])), security_group_tags)

    node_record = {
        "type": "ec2",
        "group_id": group,
        "image_id": saved_image_id if isinstance(saved_image_id, str) else None,
        "security_group_id": security_group_id,
        "expected_tags": node_tags,
        "status": "provisioning",
    }

    instance = _find_instance(ec2, node_tags)
    if instance is None:
        images = ec2.describe_images(
            Filters=[{"Name": "state", "Values": ["available"]}]
        ).get("Images", [])
        image_ids = sorted(
            image["ImageId"]
            for image in images
            if isinstance(image.get("ImageId"), str) and image["ImageId"]
        )
        if not image_ids:
            raise PermanentError("LocalStack did not provide an available mock image")
        if node_record["image_id"] is None:
            node_record["image_id"] = image_ids[0]
        elif node_record["image_id"] not in image_ids:
            raise PermanentError("Saved LocalStack mock image is no longer available")
        token = hashlib.sha256(f"ppa2-fenix:{group}:node:v1".encode("utf-8")).hexdigest()
        response = ec2.run_instances(
            ImageId=node_record["image_id"],
            InstanceType="t3.micro",
            MinCount=1,
            MaxCount=1,
            SecurityGroupIds=[security_group_id],
            ClientToken=token,
            TagSpecifications=[
                {"ResourceType": "instance", "Tags": _tag_list(node_tags)}
            ],
        )
        instance = response["Instances"][0]
    instance_id = instance.get("InstanceId")
    if not isinstance(instance_id, str) or not instance_id:
        raise PermanentError("Created EC2 instance has no identifier")
    observed_response = ec2.describe_instances(InstanceIds=[instance_id])
    observed_instances = [
        observed
        for reservation in observed_response.get("Reservations", [])
        for observed in reservation.get("Instances", [])
    ]
    if len(observed_instances) != 1:
        raise PermanentError("Created EC2 instance could not be verified")
    instance = observed_instances[0]
    observed_image_id = instance.get("ImageId")
    if not isinstance(observed_image_id, str) or not observed_image_id:
        raise PermanentError("EC2 image identifier could not be verified")
    if node_record["image_id"] is not None and observed_image_id != node_record["image_id"]:
        raise PermanentError("EC2 instance image does not match the saved lab image")
    node_record["image_id"] = observed_image_id
    _require_tags(_tags_dict(instance.get("Tags", [])), node_tags)
    security_groups = {item.get("GroupId") for item in instance.get("SecurityGroups", [])}
    if security_group_id not in security_groups:
        raise PermanentError("EC2 instance is attached to an unexpected security group")
    node_record["id"] = instance_id
    node_record["status"] = "ready"
    _save_entry(inventory, "node-01", node_record)

    bucket_tags = ownership
    _ensure_bucket(s3, inventory, group, f"fenix-{group}-demo", bucket_tags)
    return inventory


def inject_fault(alias: str) -> None:
    """Apply one verified fault only to the resource recorded for this group."""
    if not isinstance(alias, str) or alias not in {"node-01", "bucket-01"}:
        raise ValidationError("Fault alias is not authorized")
    inventory = load(INVENTORY_PATH)
    if not isinstance(inventory, dict) or not isinstance(inventory.get(alias), dict):
        raise ValidationError("Fault alias is not present in the inventory")
    resource = inventory[alias]
    if resource.get("status") != "ready":
        raise ValidationError("Resource setup is incomplete")
    group = identifier(resource.get("group_id"))
    expected = resource.get("expected_tags")
    if not isinstance(expected, dict):
        raise ValidationError("Inventory expected_tags are invalid")
    owner_markers = {
        "ManagedBy": "ppa2",
        "Project": "fenix",
        "GroupId": group,
        "Owner": group,
    }
    _require_tags(expected, owner_markers)

    if alias == "node-01" and resource.get("type") == "ec2":
        instance_id = resource.get("id")
        if not isinstance(instance_id, str) or not instance_id or instance_id == "pending":
            raise ValidationError("EC2 inventory record is incomplete")
        ec2 = client("ec2")
        response = ec2.describe_instances(InstanceIds=[instance_id])
        instances = [
            instance
            for reservation in response.get("Reservations", [])
            for instance in reservation.get("Instances", [])
        ]
        if len(instances) != 1:
            raise PermanentError("Authorized EC2 instance was not found")
        _require_tags(_tags_dict(instances[0].get("Tags", [])), expected)
        state = instances[0].get("State", {}).get("Name")
        if state == "stopped":
            return
        if state != "running":
            raise PermanentError("EC2 instance is not in a fault-injectable state")
        ec2.stop_instances(InstanceIds=[instance_id])
        for _ in range(10):
            response = ec2.describe_instances(InstanceIds=[instance_id])
            observed = response["Reservations"][0]["Instances"][0].get("State", {}).get("Name")
            if observed == "stopped":
                return
            if observed in {"terminated", "shutting-down"}:
                raise PermanentError("EC2 instance entered a terminal state during fault injection")
            time.sleep(1)
        raise PermanentError("EC2 stop was not confirmed after bounded polling")

    if alias == "bucket-01" and resource.get("type") == "s3":
        bucket_name = resource.get("id")
        if not isinstance(bucket_name, str) or not bucket_name:
            raise ValidationError("S3 inventory record is incomplete")
        if bucket_name != f"fenix-{group}-demo":
            raise PermanentError("Bucket name does not match the group inventory")
        s3 = client("s3")
        try:
            current = _tags_dict(s3.get_bucket_tagging(Bucket=bucket_name).get("TagSet", []))
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") != "NoSuchTagSet":
                raise
            raise PermanentError("Bucket ownership cannot be verified") from error
        _require_tags(current, {key: value for key, value in expected.items() if key != "Owner"})
        if current.get("Owner") is None:
            return
        if current["Owner"] != group:
            raise PermanentError("Bucket owner tag belongs to another group")
        current.pop("Owner")
        s3.put_bucket_tagging(Bucket=bucket_name, Tagging={"TagSet": _tag_list(current)})
        verified = _tags_dict(s3.get_bucket_tagging(Bucket=bucket_name).get("TagSet", []))
        if "Owner" in verified:
            raise PermanentError("Bucket fault was not confirmed")
        _require_tags(verified, {key: value for key, value in expected.items() if key != "Owner"})
        return

    raise ValidationError("Fault alias does not match its inventory resource type")
