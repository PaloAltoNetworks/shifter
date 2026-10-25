"""AWS Secrets Manager adapter implementing SecretsStore protocol."""

from __future__ import annotations

import base64
import logging
import os
from typing import Any
from uuid import UUID

import boto3
from botocore.client import BaseClient
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

from shared.cloud.aws.config import secrets_client_config
from shared.cloud.exceptions import CloudSecretsError

logger = logging.getLogger(__name__)


class AWSSecretsStore:
    """Secrets Manager implementation of SecretsStore protocol."""

    def create_owned_secret(self, source_id: UUID, version_id: UUID, value: str) -> str:
        """A new random version is a distinct immutable secret, never AWSCURRENT."""
        from shared.cloud.owned_secrets import model_source_secret_name, validate_owned_payload

        name = model_source_secret_name(source_id, version_id)
        validate_owned_payload(value)
        try:
            response = self._get_client().create_secret(
                Name=name,
                ClientRequestToken=str(version_id),
                SecretString=value,
                Tags=[{"Key": "shifter-model-source", "Value": source_id.hex}],
            )
            return response["ARN"]
        except Exception:
            raise CloudSecretsError("Failed to store model credential") from None

    def retire_owned_secret(self, source_id: UUID, version_id: UUID) -> None:
        from shared.cloud.owned_secrets import model_source_secret_name

        name = model_source_secret_name(source_id, version_id)
        try:
            self._get_client().delete_secret(SecretId=name, RecoveryWindowInDays=7)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                return
            raise CloudSecretsError("Failed to retire model credential") from None
        except Exception:
            raise CloudSecretsError("Failed to retire model credential") from None

    @staticmethod
    def _get_client() -> BaseClient:
        region: str = str(getattr(settings, "CLOUD_REGION", None) or getattr(settings, "AWS_REGION", "us-east-2"))
        endpoint_url: str | None = os.environ.get("AWS_ENDPOINT_URL") or None
        # Bounded connect/read timeouts so a stalled Secrets Manager fails fast
        # instead of blocking the calling thread on botocore's long defaults.
        return boto3.client(
            "secretsmanager",
            region_name=region,
            endpoint_url=endpoint_url,
            config=secrets_client_config(),
        )

    def get_secret(self, secret_ref: str) -> str:
        """Retrieve one pinned reference without reflecting provider diagnostics."""
        try:
            client = self._get_client()
            response: dict[str, Any] = client.get_secret_value(SecretId=secret_ref)
            if "SecretString" in response:
                return response["SecretString"]
            return base64.b64decode(response["SecretBinary"]).decode("utf-8")
        except (ClientError, BotoCoreError, ValueError, KeyError):
            raise CloudSecretsError("Failed to retrieve secret") from None
