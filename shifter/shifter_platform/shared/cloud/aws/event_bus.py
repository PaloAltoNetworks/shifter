"""AWS SNS adapter implementing EventBus protocol."""

from __future__ import annotations

import logging
import os
from typing import Any

import boto3
from botocore.client import BaseClient
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

from shared.cloud.exceptions import CloudEventBusError

logger = logging.getLogger(__name__)


class AWSEventBus:
    """SNS implementation of EventBus protocol."""

    @staticmethod
    def _get_client() -> BaseClient:
        region: str = str(getattr(settings, "CLOUD_REGION", None) or getattr(settings, "AWS_REGION", "us-east-2"))
        endpoint_url: str | None = os.environ.get("AWS_ENDPOINT_URL") or None
        return boto3.client("sns", region_name=region, endpoint_url=endpoint_url)

    def publish(
        self,
        topic_id: str,
        message: str,
        attributes: dict[str, str] | None = None,
    ) -> None:
        logger.debug("publish: topic_id=%s", topic_id)
        try:
            client = self._get_client()
            kwargs: dict[str, Any] = {
                "TopicArn": topic_id,
                "Message": message,
            }
            if attributes:
                kwargs["MessageAttributes"] = {
                    k: {"DataType": "String", "StringValue": v} for k, v in attributes.items()
                }
            client.publish(**kwargs)
            logger.info("publish: success topic_id=%s", topic_id)
        except (ClientError, BotoCoreError) as e:
            logger.exception("publish: failed topic_id=%s error=%s", topic_id, e)
            raise CloudEventBusError(f"Failed to publish to SNS: {e}") from e
