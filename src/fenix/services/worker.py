"""Worker de SQS de un solo mensaje, con gestión de etapas durables y ACK explícitos."""

import json
import logging
import re
import time

from botocore.exceptions import BotoCoreError, ClientError

from fenix.services.sqs import acknowledge, receive, retry_later
from fenix.utils.errors import ProjectError, ValidationError


_SAFE_ID = re.compile(r"[a-z0-9-]{3,32}\Z")


def _safe_id(value) -> str | None:
    return value if isinstance(value, str) and _SAFE_ID.fullmatch(value) else None


def _log(logger, level: int, message: str, context: dict) -> None:
    logger.log(
        level,
        message,
        extra={
            "event_id": context.get("event_id"),
            "message_id": context.get("message_id"),
            "resource_id": context.get("resource_id"),
            "attempt": context.get("attempt"),
            "action": context.get("action"),
            "status": context.get("status"),
        },
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(value: str):
    raise ValueError("Invalid JSON constant")


def _attempt(message: dict) -> int | None:
    try:
        value = int(message.get("Attributes", {})["ApproximateReceiveCount"])
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    return value if value > 0 else None


def _retain(url: str, message: dict, error: Exception, context: dict, logger) -> None:
    context["action"] = "change_visibility"
    context["status"] = type(error).__name__
    minimum = getattr(error, "retry_after", None)
    try:
        if type(minimum) is int and 0 <= minimum <= 30:
            delay = retry_later(url, message, minimum_delay=minimum)
        else:
            delay = retry_later(url, message)
    except (BotoCoreError, ClientError, OSError, ValueError, KeyError, TypeError) as retry_error:
        context["status"] = type(retry_error).__name__
        _log(logger, logging.ERROR, "message_visibility_update_failed", context)
        return
    context["status"] = "retrying"
    context["attempt"] = _attempt(message)
    _log(logger, logging.INFO, f"message_retained_for_{delay}_seconds", context)


def run(url: str, handler, logger, once: bool = False) -> None:
    """Consulta y procesa un mensaje a la vez; solo lo confirma si el controlador termina correctamente."""
    while True:
        try:
            messages = receive(url)
        except (BotoCoreError, ClientError, OSError, ValidationError) as error:
            context = {"action": "receive", "status": type(error).__name__}
            _log(logger, logging.ERROR, "sqs_receive_failed", context)
            if once:
                return
            time.sleep(2)
            continue

        if not isinstance(messages, list):
            context = {"action": "receive", "status": "InvalidResponse"}
            _log(logger, logging.ERROR, "sqs_receive_response_invalid", context)
            if once:
                return
            time.sleep(2)
            continue
        if not messages:
            _log(logger, logging.DEBUG, "queue_poll_empty", {"action": "receive", "status": "empty"})
            if once:
                return
            continue

        for message in messages:
            context = {
                "event_id": None,
                "message_id": message.get("MessageId") if isinstance(message, dict) else None,
                "resource_id": None,
                "attempt": _attempt(message) if isinstance(message, dict) else None,
                "action": "decode",
                "status": None,
            }
            if not isinstance(context["message_id"], str) or len(context["message_id"]) > 128:
                context["message_id"] = None
            if not isinstance(message, dict):
                error = ValidationError("SQS message is not an object")
                _log(logger, logging.WARNING, "message_rejected", {**context, "status": type(error).__name__})
                continue
            receipt = message.get("ReceiptHandle")
            if not isinstance(receipt, str) or not receipt:
                _log(logger, logging.ERROR, "message_receipt_missing", {**context, "status": "InvalidReceipt"})
                continue

            try:
                body = message.get("Body")
                if not isinstance(body, str) or len(body.encode("utf-8")) > 16_384:
                    raise ValidationError("SQS message body is invalid")
                event = json.loads(
                    body,
                    object_pairs_hook=_unique_object,
                    parse_constant=_reject_constant,
                )
                if not isinstance(event, dict):
                    raise ValidationError("SQS event must be a JSON object")
                context["event_id"] = _safe_id(event.get("event_id"))
                context["resource_id"] = _safe_id(event.get("resource_id"))
                context["action"] = "handle"
                handler(event)
            except (
                ProjectError,
                BotoCoreError,
                ClientError,
                OSError,
                ValueError,
                TypeError,
                KeyError,
                UnicodeError,
                RecursionError,
            ) as error:
                context["status"] = type(error).__name__
                _log(logger, logging.WARNING, "message_processing_failed", context)
                _retain(url, message, error, context, logger)
            else:
                context["action"] = "acknowledge"
                try:
                    acknowledge(url, receipt)
                except (BotoCoreError, ClientError, OSError, ValueError, KeyError, TypeError) as error:
                    context["status"] = type(error).__name__
                    _log(logger, logging.ERROR, "message_acknowledgement_failed", context)
                    _retain(url, message, error, context, logger)
                else:
                    context["status"] = "acknowledged"
                    _log(logger, logging.INFO, "message_acknowledged", context)

        if once:
            return
