"""Contratos de seguridad de salida para los scripts de inspección de solo lectura."""

import json
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from fenix.utils.errors import PermanentError
from scripts import check_dlq, inspect_resources, telegram_evidence


@pytest.mark.base
def test_dlq_main_redacts_identifiers_and_message_content_in_json_and_human(
    monkeypatch, capsys
):
    prefix = "queue-prefix-private-sentinel"
    work_url = "https://queue-host-private-sentinel/work-queue-resource-private"
    dlq_url = "https://queue-host-private-sentinel/dlq-resource-private"
    work_arn = "arn:aws:sqs:region:account-private:work-queue-resource-private"
    dlq_arn = "arn:aws:sqs:region:account-private:dlq-resource-private"
    body = json.dumps(
        {
            "chat_id": "chat-id-private-sentinel",
            "user_id": "user-id-private-sentinel",
            "event_id": "event-id-private-sentinel",
            "attempt": 887766554,
            "text": "payload-text-private-sentinel",
            "private_ip": "10.23.45.67",
            "tag_value": "tag-value-private-sentinel",
            "path": "/local/path-private-sentinel",
        }
    )
    queue_urls = {f"{prefix}-events": work_url, f"{prefix}-dlq": dlq_url}

    class FakeSQS:
        def get_queue_url(self, QueueName):
            return {"QueueUrl": queue_urls[QueueName]}

        def get_queue_attributes(self, QueueUrl, AttributeNames):
            if QueueUrl == work_url:
                attributes = {
                    "ApproximateNumberOfMessages": "4",
                    "ApproximateNumberOfMessagesNotVisible": "2",
                    "ApproximateNumberOfMessagesDelayed": "1",
                    "QueueArn": work_arn,
                    "RedrivePolicy": json.dumps(
                        {"maxReceiveCount": "3", "deadLetterTargetArn": dlq_arn}
                    ),
                    "VisibilityTimeout": "45",
                    "MessageRetentionPeriod": "345600",
                }
            else:
                attributes = {
                    "ApproximateNumberOfMessages": "1",
                    "ApproximateNumberOfMessagesNotVisible": "0",
                    "ApproximateNumberOfMessagesDelayed": "0",
                    "QueueArn": dlq_arn,
                    "VisibilityTimeout": "30",
                    "MessageRetentionPeriod": "1209600",
                }
            return {"Attributes": attributes}

        def receive_message(self, **kwargs):
            assert kwargs["VisibilityTimeout"] == 0
            return {
                "Messages": [
                    {
                        "MessageId": "message-id-private-sentinel",
                        "Body": body,
                        "Attributes": {
                            "ApproximateReceiveCount": "2",
                            "SentTimestamp": "1763700000000",
                        },
                    }
                ]
            }

    monkeypatch.setattr(check_dlq, "load_dotenv", lambda *_: None)
    monkeypatch.setattr(check_dlq, "client", lambda _service: FakeSQS())
    private_values = (
        prefix,
        work_url,
        dlq_url,
        "queue-host-private-sentinel",
        "work-queue-resource-private",
        "dlq-resource-private",
        "account-private",
        work_arn,
        dlq_arn,
        "message-id-private-sentinel",
        "chat-id-private-sentinel",
        "user-id-private-sentinel",
        "event-id-private-sentinel",
        "887766554",
        "payload-text-private-sentinel",
        "10.23.45.67",
        "tag-value-private-sentinel",
        "/local/path-private-sentinel",
        body,
    )

    assert check_dlq.main(["--prefix", prefix, "--peek", "--json"]) == 0
    json_output = capsys.readouterr().out
    report = json.loads(json_output)
    assert report["work_queue"]["counts"] == {
        "visible": 4,
        "not_visible": 2,
        "delayed": 1,
    }
    assert report["dlq"]["counts"]["visible"] == 1
    assert report["compliant"] is True
    assert report["work_queue"]["redrive"]["targets_dlq"] is True
    assert "prefix" not in report
    assert "url" not in report["work_queue"]
    assert "arn" not in report["dlq"]

    assert check_dlq.main(["--prefix", prefix, "--peek"]) == 0
    human_output = capsys.readouterr().out
    assert "visible=4 not_visible=2 delayed=1" in human_output
    assert "Verdict: True" in human_output
    assert "targets DLQ: True" in human_output
    for output in (json_output, human_output):
        for private_value in private_values:
            assert private_value not in output


@pytest.mark.base
def test_dlq_provider_error_hides_raw_message(monkeypatch, capsys):
    raw_error = "provider-error-private-sentinel https://private-host/path-private"

    class FailedSQS:
        def get_queue_url(self, **_kwargs):
            raise ClientError(
                {"Error": {"Code": "QueueDoesNotExist", "Message": raw_error}},
                "GetQueueUrl",
            )

    monkeypatch.setattr(check_dlq, "load_dotenv", lambda *_: None)
    monkeypatch.setattr(check_dlq, "client", lambda _service: FailedSQS())

    assert check_dlq.main(["--prefix", "safe-prefix"]) == 1
    stderr = capsys.readouterr().err
    assert "ClientError" in stderr
    assert raw_error not in stderr
    assert "private-host" not in stderr


@pytest.mark.base
def test_resource_inspection_redacts_ids_tags_and_external_paths(
    monkeypatch, tmp_path, capsys
):
    group = "private-group-marker"
    bucket_name = "private-bucket-resource-marker"
    instance_id = "i-private-resource-marker"
    security_group_id = "sg-private-resource-marker"
    private_tag_value = "private-tag-value-marker"
    inventory_path = tmp_path / "private-inventory-marker.json"
    tag_set = [
        {"Key": "ManagedBy", "Value": "ppa2"},
        {"Key": "Project", "Value": "fenix"},
        {"Key": "GroupId", "Value": group},
        {"Key": "Owner", "Value": group},
        {"Key": "Name", "Value": "private-resource-name-marker"},
        {"Key": "Environment", "Value": private_tag_value},
    ]

    class FakeS3:
        def head_bucket(self, **kwargs):
            return {}

        def get_bucket_tagging(self, **kwargs):
            return {"TagSet": tag_set}

    class FakeEC2:
        def describe_instances(self, **kwargs):
            instance = {
                "InstanceId": instance_id,
                "State": {"Name": "running"},
                "InstanceType": "t3.micro",
                "PrivateIpAddress": "10.23.45.67",
                "Tags": tag_set,
                "SecurityGroups": [{"GroupId": security_group_id}],
            }
            return {"Reservations": [{"Instances": [instance]}]}

        def describe_security_groups(self, **kwargs):
            return {
                "SecurityGroups": [
                    {
                        "GroupId": security_group_id,
                        "GroupName": "private-security-group-marker",
                        "VpcId": "vpc-private-marker",
                        "Tags": tag_set,
                    }
                ]
            }

    inventory = {
        "private-instance-alias-marker": {
            "type": "ec2",
            "group_id": group,
            "id": instance_id,
            "security_group_id": security_group_id,
        },
        "private-bucket-alias-marker": {
            "type": "s3",
            "group_id": group,
            "id": bucket_name,
        },
    }
    s3 = FakeS3()
    ec2 = FakeEC2()
    monkeypatch.setattr(inspect_resources, "load_dotenv", lambda *_: None)
    monkeypatch.setattr(inspect_resources, "load", lambda _path: inventory)
    monkeypatch.setattr(
        inspect_resources,
        "client",
        lambda service: s3 if service == "s3" else ec2,
    )

    json_args = ["--group", group, "--inventory", str(inventory_path), "--json"]
    assert inspect_resources.main(json_args) == 0
    json_output = capsys.readouterr().out
    report = json.loads(json_output)
    assert report["inventory_path"] == "<REDACTED_PATH>"
    assert report["group"] == "<TAG_VALUE>"
    assert report["summary"]["ec2"]["owned"] == 1
    assert report["summary"]["s3"]["owned"] == 2
    assert report["ec2"][0]["state"] == "running"
    assert report["ec2"][0]["private_ip"] == "<PRIVATE_IP>"
    assert "Environment" in report["ec2"][0]["tags"]
    assert report["ec2"][0]["tags"]["Environment"] == "<TAG_VALUE>"

    assert inspect_resources.main(
        ["--group", group, "--inventory", str(inventory_path)]
    ) == 0
    human_output = capsys.readouterr().out
    assert "EC2: owned=1 foreign=0 missing=0" in human_output
    assert "S3: owned=2 foreign=0 missing=0" in human_output
    assert "Verdict: OK" in human_output
    for output in (json_output, human_output):
        for private_value in (
            str(inventory_path),
            group,
            bucket_name,
            instance_id,
            security_group_id,
            private_tag_value,
            "private-resource-name-marker",
            "private-security-group-marker",
            "vpc-private-marker",
            "10.23.45.67",
            "private-instance-alias-marker",
            "private-bucket-alias-marker",
        ):
            assert private_value not in output


@pytest.mark.base
def test_resource_inspection_hides_external_path_on_inventory_error(
    monkeypatch, tmp_path, capsys
):
    inventory_path = tmp_path / "private-missing-inventory-marker.json"
    raw_error = "filesystem-error-private-sentinel"

    def fail_to_load(path):
        raise OSError(f"{raw_error}: cannot read {path}")

    monkeypatch.setattr(inspect_resources, "load_dotenv", lambda *_: None)
    monkeypatch.setattr(inspect_resources, "load", fail_to_load)

    assert (
        inspect_resources.main(
            ["--group", "private-group-marker", "--inventory", str(inventory_path)]
        )
        == 1
    )
    stderr = capsys.readouterr().err
    assert "<REDACTED_PATH>" in stderr
    assert str(inventory_path) not in stderr
    assert raw_error not in stderr


@pytest.mark.base
def test_telegram_evidence_stores_and_prints_only_safe_confirmation(
    monkeypatch, tmp_path, capsys
):
    root = tmp_path / "private-repo-path-marker"
    evidence_dir = root / "evidencias" / "telegram"
    message_text = "caller-message-text-private-sentinel"
    message_id = "telegram-message-id-private-sentinel"
    calls = []

    def fake_notify(text, *, return_result=False):
        calls.append((text, return_result))
        return {"provider": "telegram", "ok": True, "message_id": message_id}

    monkeypatch.setattr(telegram_evidence, "ROOT", root)
    monkeypatch.setattr(telegram_evidence, "DEFAULT_OUT_DIR", evidence_dir)
    monkeypatch.setattr(telegram_evidence, "load_dotenv", lambda *_: None)
    monkeypatch.setattr(telegram_evidence, "notify", fake_notify)
    monkeypatch.setenv("NOTIFY_PROVIDER", "telegram")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-private-sentinel-123456")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat-private-sentinel")

    assert telegram_evidence.main(["--text", message_text]) == 0
    stdout = capsys.readouterr().out
    evidence_files = list(evidence_dir.glob("*.json"))
    assert len(evidence_files) == 1
    evidence_text = evidence_files[0].read_text(encoding="utf-8")
    evidence = json.loads(evidence_text)
    assert evidence["status"] == "sent"
    assert evidence["telegram_response"] == {"ok": True}
    assert calls == [(message_text, True)]
    for private_value in (
        message_text,
        message_id,
        str(root),
        "token-private-sentinel-123456",
        "chat-private-sentinel",
    ):
        assert private_value not in stdout
        assert private_value not in evidence_text
    assert "Status: confirmed (provider=telegram, ok=true)." in stdout


@pytest.mark.base
def test_telegram_evidence_rejects_external_output_directory_before_sending(
    monkeypatch, tmp_path, capsys
):
    root = tmp_path / "repo"
    evidence_dir = root / "evidencias" / "telegram"
    outside_dir = tmp_path / "private-external-output-marker"
    calls = []
    monkeypatch.setattr(telegram_evidence, "ROOT", root)
    monkeypatch.setattr(telegram_evidence, "DEFAULT_OUT_DIR", evidence_dir)
    monkeypatch.setattr(telegram_evidence, "load_dotenv", lambda *_: None)
    monkeypatch.setattr(
        telegram_evidence,
        "notify",
        lambda *_args, **_kwargs: calls.append(True),
    )
    monkeypatch.setenv("NOTIFY_PROVIDER", "telegram")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-private-sentinel-123456")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat-private-sentinel")

    assert telegram_evidence.main(["--out-dir", str(outside_dir)]) == 2
    stderr = capsys.readouterr().err
    assert "within evidencias/telegram" in stderr
    assert str(outside_dir) not in stderr
    assert calls == []


@pytest.mark.base
def test_telegram_evidence_rejects_evidence_root_symlink_escape(
    monkeypatch, tmp_path, capsys
):
    root = tmp_path / "repo"
    evidence_parent = root / "evidencias"
    evidence_dir = evidence_parent / "telegram"
    outside_dir = tmp_path / "external-evidence"
    evidence_parent.mkdir(parents=True)
    outside_dir.mkdir()
    try:
        evidence_dir.symlink_to(outside_dir, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("platform or filesystem does not permit directory symlinks")

    calls = []
    monkeypatch.setattr(telegram_evidence, "ROOT", root)
    monkeypatch.setattr(telegram_evidence, "DEFAULT_OUT_DIR", evidence_dir)
    monkeypatch.setattr(telegram_evidence, "load_dotenv", lambda *_: None)
    monkeypatch.setattr(
        telegram_evidence,
        "notify",
        lambda *_args, **_kwargs: calls.append(True),
    )
    monkeypatch.setenv("NOTIFY_PROVIDER", "telegram")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-private-sentinel-123456")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat-private-sentinel")

    assert telegram_evidence.main(["--out-dir", str(evidence_dir)]) == 2
    stderr = capsys.readouterr().err
    assert "within evidencias/telegram" in stderr
    assert str(outside_dir) not in stderr
    assert calls == []
    assert list(outside_dir.iterdir()) == []


@pytest.mark.base
def test_telegram_evidence_sanitizes_provider_and_filesystem_errors(
    monkeypatch, tmp_path, capsys
):
    root = tmp_path / "repo"
    evidence_dir = root / "evidencias" / "telegram"
    raw_error = "raw-error-private-sentinel https://private-host/path"
    monkeypatch.setattr(telegram_evidence, "ROOT", root)
    monkeypatch.setattr(telegram_evidence, "DEFAULT_OUT_DIR", evidence_dir)
    monkeypatch.setattr(telegram_evidence, "load_dotenv", lambda *_: None)
    monkeypatch.setenv("NOTIFY_PROVIDER", "telegram")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-private-sentinel-123456")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat-private-sentinel")

    def fail_to_send(*_args, **_kwargs):
        raise PermanentError(raw_error)

    monkeypatch.setattr(telegram_evidence, "notify", fail_to_send)
    assert telegram_evidence.main([]) == 1
    send_stderr = capsys.readouterr().err
    assert "PermanentError" in send_stderr
    assert raw_error not in send_stderr
    assert "private-host" not in send_stderr

    monkeypatch.setattr(
        telegram_evidence,
        "notify",
        lambda *_args, **_kwargs: {"provider": "telegram", "ok": True},
    )
    original_write_text = Path.write_text

    def fail_to_write(path, *args, **kwargs):
        raise OSError(f"{raw_error}: {path}")

    monkeypatch.setattr(Path, "write_text", fail_to_write)
    assert telegram_evidence.main([]) == 1
    file_stderr = capsys.readouterr().err
    assert "OSError" in file_stderr
    assert raw_error not in file_stderr
    assert "private-host" not in file_stderr
    assert str(root) not in file_stderr
    monkeypatch.setattr(Path, "write_text", original_write_text)
