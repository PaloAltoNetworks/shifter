"""AWS Secrets Manager adapter implementing SecretsStore protocol."""

from __future__ import annotations

import base64
import logging

from botocore.exceptions import BotoCoreError, ClientError

from cloud.aws.base import BaseAWSAdapter
from cloud.exceptions import CloudSecretsError
from log_redact import safe_log_id

logger = logging.getLogger(__name__)


class AWSSecretsStore(BaseAWSAdapter):
    """Secrets Manager implementation of SecretsStore protocol."""

    _service_name = "secretsmanager"

    def get_secret(self, secret_id: str) -> str:
        logger.debug("get_secret: secret_id=%s", safe_log_id(secret_id))
        try:
            client = self._get_client()
            response = client.get_secret_value(SecretId=secret_id)
            if "SecretString" in response:
                return response["SecretString"]
            # Binary secret — base64-decode to string
            return base64.b64decode(response["SecretBinary"]).decode("utf-8")
        except (ClientError, BotoCoreError) as e:
            logger.exception("get_secret: failed secret_id=%s", safe_log_id(secret_id))
            raise CloudSecretsError(f"Failed to retrieve secret: {e}") from e
