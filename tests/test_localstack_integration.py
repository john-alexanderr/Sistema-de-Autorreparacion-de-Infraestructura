"""Opt-in LocalStack scenarios; never run without explicit course approval."""

import asyncio
import json
import logging
import os
import time
from uuid import uuid4

import httpx
import pytest
from botocore.exceptions import ClientError

from fenix.config.settings import client
from fenix.services import demo, notifications, receiver, remediation, sqs, worker
from fenix.utils.crypto import signature
from fenix.utils.state import load


def _tag_map(tags: list[dict]) -> dict[str, str]:
    return {item["Key"]: item["Value"] for item in tags}


def _event(group: str, resource: str = "node-01", event_type: str = "instance.stopped") -> dict:
    return {
        "schema_version": 1,
        "event_id": f"evt-{group}-001",
        "event_type": event_type,
        "resource_id": resource,
        "occurred_at": "2026-10-22T18:00:00Z",
        "simulate_failures": 0,
    }


def _post(body: bytes, secret: str):
    async def request():
        transport = httpx.ASGITransport(app=receiver.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as session:
            timestamp = int(time.time())
            return await session.post(
                "/webhook",
                content=body,
                headers={"X-Webhook-Signature": f"t={timestamp},v1={signature(secret, timestamp, body)}"},
            )

    return asyncio.run(request())


def _delete_owned_resources(context: dict) -> None:
    ec2 = client("ec2")
    s3 = client("s3")
    sqs_client = client("sqs")
    group = context["group"]
    inventory_path = context["inventory_path"]
    inventory = load(str(inventory_path)) if inventory_path.exists() else {}

    node = inventory.get("node-01") if isinstance(inventory, dict) else None
    if isinstance(node, dict) and node.get("group_id") == group:
        instance_id = node.get("id")
        if isinstance(instance_id, str) and instance_id.startswith("i-"):
            response = ec2.describe_instances(InstanceIds=[instance_id])
            instances = [
                item
                for reservation in response.get("Reservations", [])
                for item in reservation.get("Instances", [])
            ]
            instance_tags = _tag_map(instances[0].get("Tags", [])) if instances else {}
            if instances and all(
                instance_tags.get(key) == value
                for key, value in {
                    "ManagedBy": "ppa2",
                    "Project": "fenix",
                    "GroupId": group,
                    "Owner": group,
                }.items()
            ):
                state = instances[0].get("State", {}).get("Name")
                if state != "terminated":
                    if state != "shutting-down":
                        ec2.terminate_instances(InstanceIds=[instance_id])
                    ec2.get_waiter("instance_terminated").wait(
                        InstanceIds=[instance_id],
                        WaiterConfig={"Delay": 1, "MaxAttempts": 30},
                    )
        security_group_id = node.get("security_group_id")
        if isinstance(security_group_id, str) and security_group_id.startswith("sg-"):
            groups = ec2.describe_security_groups(GroupIds=[security_group_id]).get("SecurityGroups", [])
            group_tags = _tag_map(groups[0].get("Tags", [])) if groups else {}
            if groups and group_tags.get("ManagedBy") == "ppa2" and group_tags.get("Project") == "fenix" and group_tags.get("GroupId") == group:
                ec2.delete_security_group(GroupId=security_group_id)

    bucket = inventory.get("bucket-01") if isinstance(inventory, dict) else None
    if isinstance(bucket, dict) and bucket.get("group_id") == group:
        bucket_name = bucket.get("id")
        if isinstance(bucket_name, str):
            try:
                tags = _tag_map(s3.get_bucket_tagging(Bucket=bucket_name).get("TagSet", []))
            except ClientError as error:
                if error.response.get("Error", {}).get("Code") != "NoSuchTagSet":
                    raise
                tags = {}
            if tags.get("GroupId") == group and tags.get("ManagedBy") == "ppa2" and tags.get("Project") == "fenix":
                s3.delete_bucket(Bucket=bucket_name)

    for name in (f"{context['prefix']}-events", f"{context['prefix']}-dlq"):
        try:
            url = sqs_client.get_queue_url(QueueName=name)["QueueUrl"]
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") not in {
                "AWS.SimpleQueueService.NonExistentQueue",
                "QueueDoesNotExist",
            }:
                raise
        else:
            sqs_client.delete_queue(QueueUrl=url)


@pytest.fixture
def local_lab(monkeypatch, tmp_path):
    approved = os.getenv("FENIX_CATEDRA_APPROVED") == "1"
    enabled = os.getenv("FENIX_RUN_LOCALSTACK") == "1"
    if not approved or not enabled:
        pytest.skip("Requires FENIX_CATEDRA_APPROVED=1 and FENIX_RUN_LOCALSTACK=1")

    group = "it-" + uuid4().hex[:8]
    prefix = "fenix-" + group
    inventory_path = tmp_path / "inventory.json"
    events_path = tmp_path / "events.json"
    monkeypatch.setattr(demo, "INVENTORY_PATH", str(inventory_path))
    monkeypatch.setattr(remediation, "INVENTORY_PATH", str(inventory_path))
    monkeypatch.setattr(remediation, "EVENTS_PATH", str(events_path))
    monkeypatch.setattr(receiver, "INVENTORY_PATH", str(inventory_path))
    monkeypatch.setenv("GROUP_ID", group)
    monkeypatch.setenv("QUEUE_PREFIX", prefix)
    context = {
        "group": group,
        "prefix": prefix,
        "inventory_path": inventory_path,
        "events_path": events_path,
    }
    try:
        yield context
    finally:
        _delete_owned_resources(context)


@pytest.mark.integracion
def test_f01_queue_and_demo_setup_are_idempotent(local_lab):
    first_urls = sqs.ensure_queues(local_lab["prefix"])
    second_urls = sqs.ensure_queues(local_lab["prefix"])
    first_inventory = demo.setup_demo(local_lab["group"])
    second_inventory = demo.setup_demo(local_lab["group"])
    assert first_urls == second_urls
    assert first_inventory["node-01"]["id"] == second_inventory["node-01"]["id"]
    assert first_inventory["bucket-01"]["id"] == second_inventory["bucket-01"]["id"]
    assert {"id", "security_group_id", "expected_tags"} <= first_inventory[
        "node-01"
    ].keys()
    assert {"id", "expected_tags"} <= first_inventory["bucket-01"].keys()
    assert "instance_id" not in first_inventory["node-01"]
    assert "bucket_name" not in first_inventory["bucket-01"]
    names = client("sqs").list_queues(QueueNamePrefix=local_lab["prefix"]).get("QueueUrls", [])
    assert len(names) == 2
    work_attributes = client("sqs").get_queue_attributes(
        QueueUrl=first_urls[0],
        AttributeNames=["VisibilityTimeout", "RedrivePolicy"],
    )["Attributes"]
    dead_attributes = client("sqs").get_queue_attributes(
        QueueUrl=first_urls[1],
        AttributeNames=["QueueArn", "RedrivePolicy"],
    )["Attributes"]
    redrive_policy = json.loads(work_attributes["RedrivePolicy"])
    assert work_attributes["VisibilityTimeout"] == "45"
    assert redrive_policy["deadLetterTargetArn"] == dead_attributes["QueueArn"]
    assert redrive_policy["maxReceiveCount"] == "3"
    assert "RedrivePolicy" not in dead_attributes


@pytest.mark.integracion
def test_f02_verified_ec2_repair_durable_ledger_mocked_telegram_and_real_ack(local_lab, monkeypatch):
    work_url, _ = sqs.ensure_queues(local_lab["prefix"])
    demo.setup_demo(local_lab["group"])
    demo.inject_fault("node-01")
    notifications_sent = []
    monkeypatch.setenv("NOTIFY_PROVIDER", "telegram")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:integration-test-token-not-sent")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100123456")

    class Accepted:
        status_code = 200
        headers = {}

        def json(self):
            return {"ok": True}

    def mock_telegram(url, **kwargs):
        notifications_sent.append((url, kwargs))
        return Accepted()

    monkeypatch.setattr(notifications.requests, "post", mock_telegram)
    target = _event(local_lab["group"])
    sqs.publish(work_url, target)

    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        worker.run(work_url, remediation.handle, logging.getLogger("fenix-integration"), once=True)
        saved = load(str(local_lab["events_path"]))
        if saved.get(target["event_id"], {}).get("status") == "complete":
            break
    else:
        pytest.fail("The real SQS delivery did not reach durable completion")

    record = load(str(local_lab["events_path"]))[target["event_id"]]
    resource = load(str(local_lab["inventory_path"]))["node-01"]
    instance = client("ec2").describe_instances(InstanceIds=[resource["id"]])
    state = instance["Reservations"][0]["Instances"][0]["State"]["Name"]
    assert state == "running"
    assert record["repair_done"] is True and record["notified"] is True
    assert len(notifications_sent) == 1
    assert notifications_sent[0][1]["json"]["chat_id"] == "-100123456"
    queue_state = client("sqs").get_queue_attributes(
        QueueUrl=work_url,
        AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"],
    )["Attributes"]
    assert queue_state["ApproximateNumberOfMessages"] == "0"
    assert queue_state["ApproximateNumberOfMessagesNotVisible"] == "0"


@pytest.mark.integracion
def test_f03_bucket_repair_preserves_unrelated_tags(local_lab, monkeypatch):
    demo.setup_demo(local_lab["group"])
    resource = load(str(local_lab["inventory_path"]))["bucket-01"]
    s3 = client("s3")
    tags = s3.get_bucket_tagging(Bucket=resource["id"])["TagSet"]
    tags.append({"Key": "Department", "Value": "test-lab"})
    s3.put_bucket_tagging(Bucket=resource["id"], Tagging={"TagSet": tags})
    demo.inject_fault("bucket-01")
    monkeypatch.setattr(remediation, "notify", lambda _text: None)
    remediation.handle(
        _event(local_lab["group"], "bucket-01", "bucket.tags_missing")
    )
    repaired = _tag_map(s3.get_bucket_tagging(Bucket=resource["id"])["TagSet"])
    assert repaired["Owner"] == local_lab["group"]
    assert repaired["Department"] == "test-lab"


def _run_until_dlq(context: dict, handler, timeout: int = 120) -> str:
    work_url, dlq_url = sqs.ensure_queues(context["prefix"])
    deadline = time.monotonic() + timeout
    logger = logging.getLogger("fenix-redrive-integration")
    while time.monotonic() < deadline:
        worker.run(work_url, handler, logger, once=True)
        attributes = client("sqs").get_queue_attributes(
            QueueUrl=dlq_url,
            AttributeNames=["ApproximateNumberOfMessages"],
        )["Attributes"]
        if int(attributes["ApproximateNumberOfMessages"]) > 0:
            messages = client("sqs").receive_message(
                QueueUrl=dlq_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=0,
            ).get("Messages", [])
            if messages:
                return messages[0]["Body"]
    pytest.fail("SQS did not deliver the poison message to the DLQ before the safety timeout")


@pytest.mark.integracion
def test_f08_corrupt_direct_sqs_message_reaches_real_dlq_without_stopping_worker(local_lab):
    work_url, _ = sqs.ensure_queues(local_lab["prefix"])
    original = "{corrupt direct-to-SQS body"
    client("sqs").send_message(QueueUrl=work_url, MessageBody=original)
    observed = _run_until_dlq(local_lab, remediation.handle)
    assert observed == original


@pytest.mark.integracion
def test_f10_persistent_handler_failure_reaches_real_dlq_without_ack(local_lab):
    work_url, _ = sqs.ensure_queues(local_lab["prefix"])
    demo.setup_demo(local_lab["group"])
    target = _event(local_lab["group"])
    target["simulate_failures"] = 5
    original = json.dumps(target)
    client("sqs").send_message(QueueUrl=work_url, MessageBody=original)
    observed = _run_until_dlq(local_lab, remediation.handle)
    assert json.loads(observed) == json.loads(original)
    ledger = load(str(local_lab["events_path"]))[target["event_id"]]
    assert ledger["attempts"] >= 1
    assert ledger["repair_done"] is False
    assert ledger["notified"] is False


@pytest.mark.integracion
def test_f13_missing_local_queue_returns_503_without_acceptance(local_lab, monkeypatch):
    secret = "integration-only-secret-value"
    monkeypatch.setenv("WEBHOOK_SECRET", secret)
    monkeypatch.setenv("QUEUE_PREFIX", "missing-" + local_lab["group"])
    demo.setup_demo(local_lab["group"])
    body = json.dumps(_event(local_lab["group"]), separators=(",", ":")).encode("utf-8")
    response = _post(body, secret)
    assert response.status_code == 503
