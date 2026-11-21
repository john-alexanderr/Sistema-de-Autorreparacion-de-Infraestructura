"""Inspección de solo lectura de la cola de trabajo y la cola de mensajes fallidos de Fénix.

El script resuelve las colas configuradas, lee sus atributos y compara la política
de redirección de la cola de trabajo con el ARN de la DLQ. Nunca crea, actualiza ni
elimina colas o mensajes. La única llamada de recepción es la opción explícita
``--peek``, que usa ``VisibilityTimeout=0`` para un mensaje y nunca lo elimina.

Ejecuta desde la raíz del repositorio::

    ./.venv/bin/python scripts/check_dlq.py
    ./.venv/bin/python scripts/check_dlq.py --peek --json
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv

from fenix.config.settings import client
from fenix.utils.errors import ValidationError


_ATTRIBUTE_NAMES = [
    "ApproximateNumberOfMessages",
    "ApproximateNumberOfMessagesNotVisible",
    "ApproximateNumberOfMessagesDelayed",
    "QueueArn",
    "RedrivePolicy",
    "VisibilityTimeout",
    "MessageRetentionPeriod",
]
_COUNTS_NOTE = "SQS counts are approximate and may lag behind the actual queue state."


def _as_int(value: object) -> int | None:
    """Convierte a enteros, cuando es posible, las cadenas numéricas de atributos de SQS."""
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sent_timestamp(value: object) -> str | None:
    """Devuelve una marca de tiempo válida de SQS como ISO-8601 UTC, sin incluir la entrada sin procesar."""
    millis = _as_int(value)
    if millis is None:
        return None
    try:
        moment = datetime.fromtimestamp(millis / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return moment.isoformat()


def _queue_attributes(sqs, url: str) -> dict:
    """Lee el subconjunto aprobado de atributos de solo lectura de una cola."""
    response = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=_ATTRIBUTE_NAMES)
    attributes = response.get("Attributes", {})
    return attributes if isinstance(attributes, dict) else {}


def _counts(attributes: dict) -> dict:
    """Construye la sección de recuentos aproximados a partir de los atributos de la cola."""
    return {
        "visible": _as_int(attributes.get("ApproximateNumberOfMessages")),
        "not_visible": _as_int(attributes.get("ApproximateNumberOfMessagesNotVisible")),
        "delayed": _as_int(attributes.get("ApproximateNumberOfMessagesDelayed")),
    }


def _parse_redrive(raw: object) -> dict:
    """Interpreta la política de redirección de la cola de trabajo sin confiar en su estructura."""
    result = {
        "present": False,
        "max_receive_count": None,
        "dead_letter_target_arn": None,
        "targets_dlq": False,
        "error": None,
    }
    if not raw:
        return result
    result["present"] = True
    if not isinstance(raw, str):
        result["error"] = "RedrivePolicy is not a JSON string"
        return result
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        result["error"] = "RedrivePolicy is not valid JSON"
        return result
    if not isinstance(parsed, dict):
        result["error"] = "RedrivePolicy is not a JSON object"
        return result
    result["max_receive_count"] = _as_int(parsed.get("maxReceiveCount"))
    target = parsed.get("deadLetterTargetArn")
    result["dead_letter_target_arn"] = target if isinstance(target, str) else None
    return result


def _peek(sqs, url: str) -> dict:
    """Lee un mensaje de la DLQ y devuelve metadatos seguros, nunca su cuerpo ni su ID."""
    response = sqs.receive_message(
        QueueUrl=url,
        MaxNumberOfMessages=1,
        VisibilityTimeout=0,
        WaitTimeSeconds=0,
        MessageSystemAttributeNames=["ApproximateReceiveCount", "SentTimestamp"],
    )
    messages = response.get("Messages", [])
    if not messages:
        return {"available": False}
    message = messages[0]
    attributes = message.get("Attributes", {})
    if not isinstance(attributes, dict):
        attributes = {}
    body = message.get("Body")
    return {
        "available": True,
        "body_length_chars": len(body) if isinstance(body, str) else None,
        "receive_count": _as_int(attributes.get("ApproximateReceiveCount")),
        "sent_timestamp": _sent_timestamp(attributes.get("SentTimestamp")),
    }


def _inspect(sqs, prefix: str, peek: bool) -> tuple[dict, bool]:
    """Lee los atributos de las colas y devuelve el informe junto con el resultado de cumplimiento."""
    work_url = sqs.get_queue_url(QueueName=f"{prefix}-events")["QueueUrl"]
    dlq_url = sqs.get_queue_url(QueueName=f"{prefix}-dlq")["QueueUrl"]
    work_attributes = _queue_attributes(sqs, work_url)
    dlq_attributes = _queue_attributes(sqs, dlq_url)
    redrive = _parse_redrive(work_attributes.get("RedrivePolicy"))
    dlq_arn = dlq_attributes.get("QueueArn")
    targets_dlq = (
        isinstance(dlq_arn, str)
        and redrive["dead_letter_target_arn"] == dlq_arn
    )
    max_receive_count_ok = redrive["max_receive_count"] == 3
    dlq_has_redrive_policy = bool(dlq_attributes.get("RedrivePolicy"))
    compliant = targets_dlq and max_receive_count_ok and not dlq_has_redrive_policy
    redrive["targets_dlq"] = targets_dlq
    redrive["max_receive_count_ok"] = max_receive_count_ok
    redrive.pop("dead_letter_target_arn", None)
    result = {
        "work_queue": {
            "counts": _counts(work_attributes),
            "visibility_timeout": _as_int(work_attributes.get("VisibilityTimeout")),
            "message_retention_period": _as_int(
                work_attributes.get("MessageRetentionPeriod")
            ),
            "redrive": redrive,
        },
        "dlq": {
            "counts": _counts(dlq_attributes),
            "visibility_timeout": _as_int(dlq_attributes.get("VisibilityTimeout")),
            "message_retention_period": _as_int(
                dlq_attributes.get("MessageRetentionPeriod")
            ),
            "has_redrive_policy": dlq_has_redrive_policy,
        },
        "targets_dlq": targets_dlq,
        "max_receive_count_ok": max_receive_count_ok,
        "compliant": compliant,
        "note": _COUNTS_NOTE,
    }
    if peek:
        result["peek"] = _peek(sqs, dlq_url)
    return result, compliant


def _print_human(result: dict) -> None:
    """Presenta el informe para una persona mediante metadatos seguros del mensaje."""
    work = result["work_queue"]
    dlq = result["dlq"]
    print("Work queue:")
    print(
        "  Counts (approximate): "
        f"visible={work['counts']['visible']} "
        f"not_visible={work['counts']['not_visible']} "
        f"delayed={work['counts']['delayed']}"
    )
    print(f"  VisibilityTimeout: {work['visibility_timeout']}")
    print(f"  MessageRetentionPeriod: {work['message_retention_period']}")
    redrive = work["redrive"]
    print(f"  RedrivePolicy present: {redrive['present']}")
    print(f"  maxReceiveCount: {redrive['max_receive_count']}")
    print(f"  maxReceiveCount is 3: {redrive['max_receive_count_ok']}")
    print(f"  targets DLQ: {redrive['targets_dlq']}")
    if redrive["error"]:
        print(f"  RedrivePolicy error: {redrive['error']}")
    print()
    print("DLQ:")
    print(
        "  Counts (approximate): "
        f"visible={dlq['counts']['visible']} "
        f"not_visible={dlq['counts']['not_visible']} "
        f"delayed={dlq['counts']['delayed']}"
    )
    print(f"  VisibilityTimeout: {dlq['visibility_timeout']}")
    print(f"  MessageRetentionPeriod: {dlq['message_retention_period']}")
    print(f"  Has RedrivePolicy: {dlq['has_redrive_policy']}")
    print()
    print(f"Verdict: {result['compliant']}")
    print(f"Note: {result['note']}")
    if "peek" in result:
        peek = result["peek"]
        print()
        if not peek["available"]:
            print("DLQ peek: no messages available.")
        else:
            print("DLQ peek (VisibilityTimeout=0; message not deleted):")
            print(f"  Body length (characters): {peek['body_length_chars']}")
            print(f"  ApproximateReceiveCount: {peek['receive_count']}")
            print(f"  SentTimestamp: {peek['sent_timestamp']}")


def _describe_error(error: Exception) -> str:
    """Devuelve únicamente la clase del error, nunca el proveedor ni el texto de la excepción."""
    return type(error).__name__


def _build_parser() -> argparse.ArgumentParser:
    """Crea el analizador de la CLI después de disponer de los valores de .env para usarlos como predeterminados."""
    parser = argparse.ArgumentParser(
        description="Inspect the Fénix work queue and DLQ without mutating them.",
    )
    parser.add_argument(
        "--prefix",
        default=os.getenv("QUEUE_PREFIX"),
        help="Queue prefix (default: QUEUE_PREFIX from .env).",
    )
    parser.add_argument(
        "--peek",
        action="store_true",
        help=(
            "Read one DLQ message with VisibilityTimeout=0 without deleting it; "
            "print safe metadata only."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print only the JSON report on stdout.",
    )
    return parser


def main(argv=None) -> int:
    """Ejecuta la inspección de solo lectura de las colas y devuelve un código de salida del proceso."""
    load_dotenv(ROOT / ".env")
    parser = _build_parser()
    args = parser.parse_args(argv)
    prefix = args.prefix
    if not prefix:
        print(
            "Missing configuration: QUEUE_PREFIX is not set. "
            "Set it in .env or pass --prefix.",
            file=sys.stderr,
        )
        return 2
    try:
        sqs = client("sqs")
    except ValidationError as error:
        print(f"Missing configuration: {_describe_error(error)}", file=sys.stderr)
        return 2
    try:
        result, compliant = _inspect(sqs, prefix, args.peek)
    except (ClientError, BotoCoreError, ValidationError) as error:
        print(f"Operational error: {_describe_error(error)}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _print_human(result)
    return 0 if compliant else 1


if __name__ == "__main__":
    raise SystemExit(main())
