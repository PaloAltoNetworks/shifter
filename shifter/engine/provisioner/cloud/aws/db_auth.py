"""AWS RDS IAM adapter implementing DBAuth protocol.

The actual RDS IAM logic will be extracted from provisioner/config.py in
Sub-Issue 6 (#816). This stub satisfies the protocol interface.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from cloud.exceptions import CloudDBAuthError

logger = logging.getLogger(__name__)


class AWSDBAuth:
    """RDS IAM implementation of DBAuth protocol."""

    def _get_client(self) -> Any:
        region: str = os.environ.get("AWS_REGION", "us-east-2")
        endpoint_url: str | None = os.environ.get("AWS_ENDPOINT_URL") or None
        return boto3.client("rds", region_name=region, endpoint_url=endpoint_url)

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
