"""AWS SSM Parameter Store adapter implementing ConfigStore protocol."""

from __future__ import annotations

import logging
import os
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from cloud.exceptions import CloudConfigStoreError

logger = logging.getLogger(__name__)


class AWSConfigStore:
    """SSM Parameter Store implementation of ConfigStore protocol."""

    def _get_client(self) -> Any:
        region: str = os.environ.get("AWS_REGION", "us-east-2")
        endpoint_url: str | None = os.environ.get("AWS_ENDPOINT_URL") or None
        return boto3.client("ssm", region_name=region, endpoint_url=endpoint_url)

    def get_parameter(self, name: str) -> str:
        logger.debug("get_parameter: name=%s", name)
        try:
            client = self._get_client()
            response: dict[str, Any] = client.get_parameter(Name=name, WithDecryption=True)
            value: str = response["Parameter"]["Value"]
            return value
        except (ClientError, BotoCoreError) as e:
            logger.error("get_parameter: failed name=%s error=%s", name, e)
            raise CloudConfigStoreError(f"Failed to get SSM parameter: {e}") from e
