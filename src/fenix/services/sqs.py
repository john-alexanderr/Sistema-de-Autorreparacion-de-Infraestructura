"""Standard SQS queue operations for Fénix."""

import json

from botocore.exceptions import ClientError

from fenix.config.settings import client
from fenix.utils.validation import identifier


_NOT_FOUND_CODES = {"AWS.SimpleQueueService.NonExistentQueue", "QueueDoesNotExist"}


def _ensure_queue(sqs, name: str, attributes: dict[str, str]) -> str:
    try:
        url = sqs.get_queue_url(QueueName=name)["QueueUrl"]
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code")
        if code not in _NOT_FOUND_CODES:
            raise
        url = sqs.create_queue(QueueName=name, Attributes=attributes)["QueueUrl"]
    sqs.set_queue_attributes(QueueUrl=url, Attributes=attributes)
    return url


def ensure_queues(prefix: str) -> tuple[str, str]:
    """Create or reconcile one standard work queue and its standard DLQ."""
    identifier(prefix)
    sqs = client("sqs")
    dead_url = _ensure_queue(
        sqs,
        f"{prefix}-dlq",
        {"MessageRetentionPeriod": "1209600"},
    )
    dead_arn = sqs.get_queue_attributes(
        QueueUrl=dead_url,
        AttributeNames=["QueueArn"],
    )["Attributes"]["QueueArn"]
    work_url = _ensure_queue(
        sqs,
        f"{prefix}-events",
        {"VisibilityTimeout": "45", "MessageRetentionPeriod": "345600"},
    )
    policy = {
        "deadLetterTargetArn": dead_arn,
        "maxReceiveCount": "3",
    }
    sqs.set_queue_attributes(
        QueueUrl=work_url,
        Attributes={"RedrivePolicy": json.dumps(policy, separators=(",", ":"))},
    )
    return work_url, dead_url


def queue_url(prefix: str) -> str:
    """Return the current URL for a previously initialized work queue."""
    identifier(prefix)
    return client("sqs").get_queue_url(QueueName=f"{prefix}-events")["QueueUrl"]


def publish(url: str, event: dict, delay: int = 0) -> str:
    """Publish a validated event and return the SQS-assigned message ID."""
    if type(delay) is not int or not 0 <= delay <= 900:
        raise ValueError("DelaySeconds must be an integer from 0 to 900")
    response = client("sqs").send_message(
        QueueUrl=url,
        MessageBody=json.dumps(event, separators=(",", ":")),
        DelaySeconds=delay,
        MessageAttributes={
            "EventId": {
                "DataType": "String",
                "StringValue": event["event_id"],
            }
        },
    )
    return response["MessageId"]


def receive(url: str) -> list[dict]:
    """Long-poll for at most one message and expose the current receipt handle."""
    response = client("sqs").receive_message(
        QueueUrl=url,
        MaxNumberOfMessages=1,
        WaitTimeSeconds=10,
        VisibilityTimeout=45,
        MessageSystemAttributeNames=["ApproximateReceiveCount"],
        MessageAttributeNames=["All"],
    )
    return response.get("Messages", [])


def acknowledge(url: str, receipt: str) -> None:
    """Delete a message only with the receipt handle from its latest delivery."""
    client("sqs").delete_message(QueueUrl=url, ReceiptHandle=receipt)


def retry_later(
    url: str,
    message: dict,
    minimum_delay: int | None = None,
) -> int:
    """Change visibility using receive-count backoff, optionally honoring Retry-After."""
    attributes = message.get("Attributes")
    receipt = message.get("ReceiptHandle")
    if not isinstance(attributes, dict) or not isinstance(receipt, str) or not receipt:
        raise ValueError("SQS message is missing retry metadata")
    try:
        count = int(attributes["ApproximateReceiveCount"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("SQS message has an invalid receive count") from error
    if count < 1:
        raise ValueError("SQS receive count must be positive")
    delay = min(30, 2 ** min(count, 5))
    if minimum_delay is not None:
        if type(minimum_delay) is not int or minimum_delay < 0:
            raise ValueError("minimum_delay must be a non-negative integer")
        delay = min(30, max(delay, minimum_delay))
    client("sqs").change_message_visibility(
        QueueUrl=url,
        ReceiptHandle=receipt,
        VisibilityTimeout=delay,
    )
    return delay
