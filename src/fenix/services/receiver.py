"""Authenticated FastAPI webhook that accepts events only after SQS confirms them."""

import json
import logging
import os
import time
from contextlib import asynccontextmanager

from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from fenix.services.events import validate
from fenix.services.sqs import publish, queue_url
from fenix.utils.crypto import verify
from fenix.utils.errors import ValidationError
from fenix.utils.logging_json import setup as setup_logging
from fenix.utils.state import load


load_dotenv()
INVENTORY_PATH = "data/inventory.json"


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    _logger, listener = setup_logging("fenix-receiver")
    try:
        yield
    finally:
        listener.stop()


app = FastAPI(title="Fénix webhook receiver", lifespan=_lifespan)
logger = logging.getLogger("fenix-receiver")


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(value: str):
    raise ValueError(f"Invalid JSON constant: {value}")


def _enqueue(event: dict) -> tuple[str, str]:
    url = queue_url(os.getenv("QUEUE_PREFIX", ""))
    return url, publish(url, event)


@app.post("/webhook", status_code=202)
async def webhook(request: Request) -> dict:
    """Authenticate raw request bytes, validate the event, and publish it once."""
    started_at = time.perf_counter()
    raw = await request.body()
    if len(raw) > 16_384:
        raise HTTPException(status_code=413, detail="Request body is too large")

    signature_headers = request.headers.getlist("x-webhook-signature")
    if len(signature_headers) != 1:
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    try:
        verify(os.getenv("WEBHOOK_SECRET", ""), signature_headers[0], raw)
    except ValidationError:
        raise HTTPException(status_code=401, detail="Invalid webhook signature") from None

    try:
        event = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid JSON request body") from None

    try:
        inventory = await run_in_threadpool(load, INVENTORY_PATH)
    except (OSError, ValueError):
        raise HTTPException(status_code=503, detail="Resource inventory is unavailable") from None
    if not isinstance(inventory, dict) or not inventory:
        raise HTTPException(status_code=503, detail="Resource inventory is unavailable")
    try:
        validated = validate(event, inventory)
    except ValidationError:
        raise HTTPException(status_code=422, detail="Event contract is invalid") from None

    try:
        _, message_id = await run_in_threadpool(_enqueue, validated)
    except (BotoCoreError, ClientError, OSError, ValidationError, ValueError, KeyError):
        raise HTTPException(status_code=503, detail="Event queue is unavailable") from None
    latency_ms = (time.perf_counter() - started_at) * 1000
    logger.info(
        "webhook_published",
        extra={
            "event_id": validated["event_id"],
            "message_id": message_id,
            "resource_id": validated["resource_id"],
            "action": "publish",
            "status": "accepted",
            "latency_ms": latency_ms,
        },
    )
    return {
        "status": "accepted",
        "event_id": validated["event_id"],
        "message_id": message_id,
    }
