"""Pruebas sin conexión de puntos de control de aprovisionamiento y recuperación de LocalStack."""

from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError

from fenix.services import cloud_support, demo
from fenix.utils.errors import PermanentError
from fenix.utils.state import load, save


GROUP = "grupo-01"
OWNERSHIP = {
    "ManagedBy": "ppa2",
    "Project": "fenix",
    "GroupId": GROUP,
    "Owner": GROUP,
}


def _tag_map(tags):
    return {item["Key"]: item["Value"] for item in tags}


def _service_error(operation: str, code: str = "ServiceUnavailable") -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": "sanitized test service error"}},
        operation,
    )


def _owned_instance(
    instance_id: str,
    image_id: str,
    security_group_id: str,
    tags: dict,
    client_token: str,
) -> dict:
    return {
        "InstanceId": instance_id,
        "ImageId": image_id,
        "ClientToken": client_token,
        "Tags": [{"Key": key, "Value": value} for key, value in tags.items()],
        "SecurityGroups": [{"GroupId": security_group_id}],
        "State": {"Name": "running"},
    }


class FakeEC2:
    def __init__(self, images=None):
        self.images = images or []
        self.group_id = "sg-created"
        self.group = None
        self.instance = None
        self.token_instance = None
        self.run_arguments = None
        self.instance_id_queries = []
        self.filter_queries = []
        self.on_run = None
        self.on_describe_id = None
        self.fail_instance_describe = False

    def describe_vpcs(self, **_kwargs):
        return {"Vpcs": [{"VpcId": "vpc-current"}]}

    def describe_security_groups(self, GroupIds=None, Filters=None):
        if GroupIds is not None:
            return {
                "SecurityGroups": [
                    self.group
                    for group_id in GroupIds
                    if self.group is not None
                    and self.group["GroupId"] == group_id
                ]
            }
        self.filter_queries.append(Filters)
        if self.group is None:
            return {"SecurityGroups": []}
        tags = _tag_map(self.group.get("Tags", []))
        matches = all(
            tags.get(item["Name"][4:]) in item["Values"]
            for item in Filters
            if item["Name"].startswith("tag:")
        )
        return {"SecurityGroups": [self.group] if matches else []}

    def create_security_group(self, **kwargs):
        self.group = {
            "GroupId": self.group_id,
            "VpcId": kwargs["VpcId"],
            "GroupName": kwargs["GroupName"],
            "Tags": kwargs["TagSpecifications"][0]["Tags"],
        }
        return {"GroupId": self.group_id}

    def describe_instances(self, Filters=None, InstanceIds=None):
        if Filters is not None:
            self.filter_queries.append(Filters)
            filters_by_name = {item["Name"]: item["Values"] for item in Filters}
            candidates = [self.instance, self.token_instance]
            matches = []
            for candidate in candidates:
                if candidate is None:
                    continue
                tags = _tag_map(candidate.get("Tags", []))
                if "client-token" in filters_by_name:
                    if candidate.get("ClientToken") not in filters_by_name["client-token"]:
                        continue
                elif not all(
                    tags.get(name[4:]) in values
                    for name, values in filters_by_name.items()
                    if name.startswith("tag:")
                ):
                    continue
                matches.append(candidate)
            return {"Reservations": [{"Instances": matches}] if matches else []}

        self.instance_id_queries.extend(InstanceIds or [])
        if self.on_describe_id is not None:
            self.on_describe_id(InstanceIds)
        if self.fail_instance_describe:
            raise _service_error("DescribeInstances")
        matches = [
            self.instance
            for instance_id in InstanceIds or []
            if self.instance is not None and self.instance["InstanceId"] == instance_id
        ]
        return {"Reservations": [{"Instances": matches}] if matches else []}

    def describe_images(self, **_kwargs):
        return {"Images": self.images}

    def run_instances(self, **kwargs):
        self.run_arguments = kwargs
        if self.on_run is not None:
            self.on_run(kwargs)
        self.instance = _owned_instance(
            "i-created",
            kwargs["ImageId"],
            kwargs["SecurityGroupIds"][0],
            _tag_map(kwargs["TagSpecifications"][0]["Tags"]),
            kwargs["ClientToken"],
        )
        return {"Instances": [{"InstanceId": self.instance["InstanceId"]}]}


class FakeS3:
    def __init__(self):
        self.meta = SimpleNamespace(region_name="us-east-1")
        self.tags = None
        self.on_create = None
        self.on_put = None
        self.fail_put = False

    def create_bucket(self, **_kwargs):
        if self.on_create is not None:
            self.on_create()

    def get_bucket_tagging(self, **_kwargs):
        if self.tags is None:
            raise _service_error("GetBucketTagging", "NoSuchTagSet")
        return {"TagSet": self.tags}

    def put_bucket_tagging(self, **kwargs):
        if self.on_put is not None:
            self.on_put()
        if self.fail_put:
            raise _service_error("PutBucketTagging")
        self.tags = kwargs["Tagging"]["TagSet"]


def _configure(monkeypatch, tmp_path, ec2, s3, initial_inventory=None):
    inventory_path = tmp_path / "inventory.json"
    if initial_inventory is not None:
        save(str(inventory_path), initial_inventory)
    clients = {"ec2": ec2, "s3": s3}
    monkeypatch.setattr(demo, "INVENTORY_PATH", str(inventory_path))
    monkeypatch.setattr(demo, "client", lambda service: clients[service])
    monkeypatch.setattr(cloud_support, "client", lambda service: clients[service])
    return inventory_path


@pytest.mark.base
def test_security_group_checkpoint_survives_unavailable_mock_images(monkeypatch, tmp_path):
    ec2 = FakeEC2()
    inventory_path = _configure(monkeypatch, tmp_path, ec2, FakeS3())

    with pytest.raises(PermanentError, match="available mock image"):
        demo.setup_demo(GROUP)

    node = load(str(inventory_path))["node-01"]
    assert node["status"] == "provisioning"
    assert node["security_group_id"] == "sg-created"
    assert node["security_group_expected_tags"] == {
        **OWNERSHIP,
        "Name": f"fenix-{GROUP}-sg",
    }
    assert all(node["expected_tags"][key] == value for key, value in OWNERSHIP.items())
    assert "id" not in node


@pytest.mark.base
def test_image_and_canonical_instance_id_are_checkpointed_before_verification(
    monkeypatch, tmp_path
):
    ec2 = FakeEC2(images=[{"ImageId": "ami-current", "State": "available"}])
    ec2.fail_instance_describe = True
    s3 = FakeS3()
    inventory_path = _configure(monkeypatch, tmp_path, ec2, s3)
    run_checkpoint = []
    describe_checkpoint = []

    def inspect_run(arguments):
        node = load(str(inventory_path))["node-01"]
        run_checkpoint.append(node.copy())
        assert node["status"] == "provisioning"
        assert node["image_id"] == arguments["ImageId"] == "ami-current"
        assert node["client_token"] == arguments["ClientToken"]
        assert "id" not in node

    def inspect_describe(instance_ids):
        node = load(str(inventory_path))["node-01"]
        describe_checkpoint.append(node.copy())
        assert instance_ids == ["i-created"]
        assert node["id"] == "i-created"
        assert node["status"] == "provisioning"

    ec2.on_run = inspect_run
    ec2.on_describe_id = inspect_describe

    with pytest.raises(ClientError):
        demo.setup_demo(GROUP)

    assert len(run_checkpoint) == 1
    assert len(describe_checkpoint) == 1
    saved = load(str(inventory_path))["node-01"]
    assert saved["status"] == "provisioning"
    assert saved["id"] == "i-created"
    assert saved["image_id"] == "ami-current"


@pytest.mark.base
def test_reset_reselects_available_image_and_reconciles_stale_ids(monkeypatch, tmp_path):
    previous_token = "a" * 64
    previous = {
        "node-01": {
            "type": "ec2",
            "group_id": GROUP,
            "id": "i-stale",
            "security_group_id": "sg-stale",
            "image_id": "ami-unavailable",
            "client_token": previous_token,
            "expected_tags": {**OWNERSHIP, "Name": f"fenix-{GROUP}-node"},
            "status": "ready",
        }
    }
    ec2 = FakeEC2(
        images=[
            {"ImageId": "ami-current-z", "State": "available"},
            {"ImageId": "ami-current-a", "State": "available"},
        ]
    )
    inventory_path = _configure(monkeypatch, tmp_path, ec2, FakeS3(), previous)
    launch_checkpoint = []

    def inspect_run(arguments):
        node = load(str(inventory_path))["node-01"]
        launch_checkpoint.append(node.copy())
        assert node["status"] == "provisioning"
        assert node["image_id"] == arguments["ImageId"] == "ami-current-a"
        assert node["security_group_id"] == arguments["SecurityGroupIds"][0] == "sg-created"
        assert node["client_token"] == arguments["ClientToken"]
        assert arguments["ClientToken"] != previous_token
        assert "id" not in node

    ec2.on_run = inspect_run

    inventory = demo.setup_demo(GROUP)

    assert len(launch_checkpoint) == 1
    assert not any("i-stale" == instance_id for instance_id in ec2.instance_id_queries)
    assert any(
        "client-token" in {item["Name"] for item in filters}
        and previous_token in next(item["Values"] for item in filters if item["Name"] == "client-token")
        for filters in ec2.filter_queries
    )
    node = inventory["node-01"]
    assert node["id"] == "i-created"
    assert node["security_group_id"] == "sg-created"
    assert node["image_id"] == "ami-current-a"
    assert node["status"] == "ready"


@pytest.mark.base
def test_client_token_match_with_foreign_tags_is_never_adopted(monkeypatch, tmp_path):
    previous_token = "b" * 64
    previous = {
        "node-01": {
            "type": "ec2",
            "group_id": GROUP,
            "id": "i-stale",
            "security_group_id": "sg-stale",
            "image_id": "ami-old",
            "client_token": previous_token,
            "expected_tags": {**OWNERSHIP, "Name": f"fenix-{GROUP}-node"},
            "status": "ready",
        }
    }
    ec2 = FakeEC2(images=[{"ImageId": "ami-current", "State": "available"}])
    ec2.token_instance = _owned_instance(
        "i-foreign",
        "ami-foreign",
        "sg-foreign",
        {"ManagedBy": "other", "Project": "other", "GroupId": "other", "Owner": "other"},
        previous_token,
    )
    inventory_path = _configure(monkeypatch, tmp_path, ec2, FakeS3(), previous)

    with pytest.raises(PermanentError, match="ownership tags"):
        demo.setup_demo(GROUP)

    assert ec2.run_arguments is None
    node = load(str(inventory_path))["node-01"]
    assert node["status"] == "provisioning"
    assert node["security_group_id"] == "sg-created"


@pytest.mark.base
def test_bucket_creation_and_tagging_keep_separate_inventory_checkpoints(
    monkeypatch, tmp_path
):
    inventory_path = tmp_path / "inventory.json"
    monkeypatch.setattr(demo, "INVENTORY_PATH", str(inventory_path))
    s3 = FakeS3()
    s3.fail_put = True
    checkpoints = []
    s3.on_create = lambda: checkpoints.append(load(str(inventory_path))["bucket-01"].copy())
    s3.on_put = lambda: checkpoints.append(load(str(inventory_path))["bucket-01"].copy())
    inventory = {}

    with pytest.raises(ClientError):
        demo._ensure_bucket(s3, inventory, GROUP, f"fenix-{GROUP}-demo", OWNERSHIP)

    assert checkpoints[0]["status"] == "provisioning"
    assert checkpoints[0]["created_by_setup"] is False
    assert checkpoints[1]["status"] == "provisioning"
    assert checkpoints[1]["created_by_setup"] is True
    saved = load(str(inventory_path))["bucket-01"]
    assert saved["status"] == "provisioning"
    assert saved["created_by_setup"] is True
