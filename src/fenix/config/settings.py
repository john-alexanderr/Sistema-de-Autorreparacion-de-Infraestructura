"""Fail-closed configuration for the local LocalStack endpoint."""

import os
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from dotenv import load_dotenv

from fenix.utils.errors import ValidationError


def client(service: str):
    """Build a Boto3 client restricted to loopback port 4566.

    Python runs on the host, so the application does not use container service
    names, AWS profiles, or credentials from a real AWS account.
    """
    load_dotenv()
    endpoint = os.environ.get("AWS_ENDPOINT_URL", "")
    try:
        parsed = urlparse(endpoint)
        port = parsed.port
    except ValueError as error:
        raise ValidationError("Invalid local AWS endpoint") from error
    if (
        parsed.scheme != "http"
        or parsed.hostname not in ("localhost", "127.0.0.1")
        or port != 4566
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValidationError("AWS_ENDPOINT_URL must target loopback port 4566")
    if service not in {"sqs", "s3", "ec2"}:
        raise ValidationError("Unsupported local AWS service")
    region = os.environ.get("AWS_DEFAULT_REGION")
    if not region:
        raise ValidationError("Missing AWS_DEFAULT_REGION")
    access_key_id = os.environ.get("AWS_ACCESS_KEY_ID", "")
    secret_access_key = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
    if not access_key_id:
        raise ValidationError("Missing AWS_ACCESS_KEY_ID")
    if not secret_access_key:
        raise ValidationError("Missing AWS_SECRET_ACCESS_KEY")
    if access_key_id != "test" or secret_access_key != "test":
        raise ValidationError("Invalid AWS credentials configuration")
    return boto3.client(
        service,
        endpoint_url=endpoint,
        region_name=region,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        config=Config(
            connect_timeout=2,
            read_timeout=15,
            retries={"mode": "standard", "total_max_attempts": 2},
            s3={"addressing_style": "path"},
        ),
    )
