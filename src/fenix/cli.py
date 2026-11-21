"""Ciclo de vida de la CLI de Fénix: configuración, inyección de fallos, envío y procesamiento."""

import argparse
import json
import os
from pathlib import Path
import requests
import sys
import time

from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv

from fenix.services import demo, remediation, sqs, worker
from fenix.utils.crypto import signature
from fenix.utils.errors import ProjectError
from fenix.utils.logging_json import setup


def main() -> int:
    """Ejecuta un comando de la CLI y siempre detiene el listener de registros del proceso."""
    load_dotenv()
    parser = argparse.ArgumentParser(description="Fénix infrastructure self-repair lab")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-queues")
    sub.add_parser("setup-demo")
    fault = sub.add_parser("fault")
    fault.add_argument("alias", choices=["node-01", "bucket-01"])
    send = sub.add_parser("send")
    send.add_argument("file")
    consume = sub.add_parser("worker")
    consume.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logger, listener = setup("fenix-" + args.command)
    code = 0
    try:
        prefix = os.environ.get("QUEUE_PREFIX", "")
        if args.command == "init-queues":
            print(sqs.ensure_queues(prefix))
        elif args.command == "setup-demo":
            print(demo.setup_demo(os.environ["GROUP_ID"]))
        elif args.command == "fault":
            demo.inject_fault(args.alias)
        elif args.command == "send":
            body = Path(args.file).read_bytes()
            json.loads(body)
            timestamp = int(time.time())
            digest = signature(os.environ["WEBHOOK_SECRET"], timestamp, body)
            response = requests.post(
                "http://127.0.0.1:8000/webhook",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Webhook-Signature": f"t={timestamp},v1={digest}",
                },
                timeout=(2, 15),
            )
            response.raise_for_status()
            print(response.status_code, response.text)
        elif args.command == "worker":
            worker.run(sqs.queue_url(prefix), remediation.handle, logger, args.once)
    except KeyboardInterrupt:
        logger.info("operator_stop", extra={"action": "shutdown", "status": "interrupted"})
    except (
        ProjectError,
        BotoCoreError,
        ClientError,
        OSError,
        ValueError,
        KeyError,
        requests.RequestException,
    ) as error:
        logger.error(
            "controlled_failure",
            extra={"action": args.command, "status": type(error).__name__},
        )
        print("Check configuration and local service status:", type(error).__name__)
        code = 1
    finally:
        listener.stop()
    return code


if __name__ == "__main__":
    sys.exit(main())
