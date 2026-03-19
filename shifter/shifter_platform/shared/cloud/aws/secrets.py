"""AWS Secrets Manager adapter implementing SecretsStore protocol.

The actual Secrets Manager logic will be extracted from engine/secrets.py
in Sub-Issue 5 (#815). This stub satisfies the protocol interface so the
factory can return it.
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

from shared.cloud.exceptions import CloudSecretsError

logger = logging.getLogger(__name__)


class AWSSecretsStore:
    """Secrets Manager implementation of SecretsStore protocol."""

    def _get_client(self) -> Any:
        region: str = str(getattr(settings, "CLOUD_REGION", None) or getattr(settings, "AWS_REGION", "us-east-2"))
        endpoint_url: str | None = os.environ.get("AWS_ENDPOINT_URL") or None
        return boto3.client("secretsmanager", region_name=region, endpoint_url=endpoint_url)

    def get_secret(self, secret_id: str) -> str:
        logger.debug("get_secret: secret_id=%s", secret_id)
        try:
            client = self._get_client()
            response: dict[str, Any] = client.get_secret_value(SecretId=secret_id)
            if "SecretString" in response:
                return response["SecretString"]
            return base64.b64decode(response["SecretBinary"]).decode("utf-8")
        except (ClientError, BotoCoreError) as e:
            logger.exception("get_secret: failed secret_id=%s", secret_id)
            raise CloudSecretsError(f"Failed to retrieve secret: {e}") from e
