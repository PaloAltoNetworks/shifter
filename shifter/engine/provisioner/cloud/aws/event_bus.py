"""AWS SNS adapter implementing EventBus protocol."""

from __future__ import annotations

import logging
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from cloud.aws.base import BaseAWSAdapter
from cloud.exceptions import CloudEventBusError

logger = logging.getLogger(__name__)


class AWSEventBus(BaseAWSAdapter):
    """SNS implementation of EventBus protocol."""

    _service_name = "sns"

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
            logger.error("publish: failed topic_id=%s error=%s", topic_id, e)
            raise CloudEventBusError(f"Failed to publish to SNS: {e}") from e
