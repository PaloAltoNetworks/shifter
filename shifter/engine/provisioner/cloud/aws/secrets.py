"""AWS Secrets Manager adapter implementing SecretsStore protocol."""

from __future__ import annotations

import base64
import logging
import os
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from cloud.exceptions import CloudSecretsError

logger = logging.getLogger(__name__)


class AWSSecretsStore:
    """Secrets Manager implementation of SecretsStore protocol."""

    def _get_client(self) -> Any:
        region: str = os.environ.get("AWS_REGION", "us-east-2")
        endpoint_url: str | None = os.environ.get("AWS_ENDPOINT_URL") or None
        return boto3.client("secretsmanager", region_name=region, endpoint_url=endpoint_url)

    def get_secret(self, secret_id: str) -> str:
        logger.debug("get_secret: secret_id=%s", secret_id)
        try:
            client = self._get_client()
            response = client.get_secret_value(SecretId=secret_id)
            if "SecretString" in response:
                return response["SecretString"]
            # Binary secret — base64-decode to string
            return base64.b64decode(response["SecretBinary"]).decode("utf-8")
        except (ClientError, BotoCoreError) as e:
            logger.error("get_secret: failed secret_id=%s error=%s", secret_id, e)
            raise CloudSecretsError(f"Failed to retrieve secret: {e}") from e
