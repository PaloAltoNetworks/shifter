"""AWS RDS IAM adapter implementing DBAuth protocol."""

from __future__ import annotations

import logging
import os

from botocore.exceptions import BotoCoreError, ClientError

from cloud.aws.base import BaseAWSAdapter
from cloud.exceptions import CloudDBAuthError

logger = logging.getLogger(__name__)


class AWSDBAuth(BaseAWSAdapter):
    """RDS IAM implementation of DBAuth protocol."""

    _service_name = "rds"

    def generate_auth_token(
        self,
        hostname: str,
        port: int,
        username: str,
    ) -> str:
        logger.debug("generate_auth_token: hostname=%s port=%d username=%s", hostname, port, username)
        try:
            client = self._get_client()
            region: str = os.environ.get("AWS_REGION", "us-east-2")
            token: str = client.generate_db_auth_token(
                DBHostname=hostname,
                Port=port,
                DBUsername=username,
                Region=region,
            )
            return token
        except (ClientError, BotoCoreError) as e:
            logger.error("generate_auth_token: failed hostname=%s error=%s", hostname, e)
            raise CloudDBAuthError(f"Failed to generate RDS IAM auth token: {e}") from e
