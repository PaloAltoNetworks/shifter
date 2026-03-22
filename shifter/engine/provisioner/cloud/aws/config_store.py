"""AWS SSM Parameter Store adapter implementing ConfigStore protocol."""

from __future__ import annotations

import logging
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from cloud.aws.base import BaseAWSAdapter
from cloud.exceptions import CloudConfigStoreError

logger = logging.getLogger(__name__)


class AWSConfigStore(BaseAWSAdapter):
    """SSM Parameter Store implementation of ConfigStore protocol."""

    _service_name = "ssm"

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
