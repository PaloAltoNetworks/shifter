"""AWS SQS adapter implementing QueueConsumer and QueuePublisher protocols."""

from __future__ import annotations

import logging
import os
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

from shared.cloud.exceptions import CloudQueueError

logger = logging.getLogger(__name__)


class AWSQueueConsumer:
    """SQS implementation of QueueConsumer protocol."""

    def _get_client(self) -> Any:
        region: str = str(getattr(settings, "CLOUD_REGION", None) or getattr(settings, "AWS_REGION", "us-east-2"))
        endpoint_url: str | None = os.environ.get("AWS_ENDPOINT_URL") or None
        return boto3.client("sqs", region_name=region, endpoint_url=endpoint_url)

    def receive_messages(
        self,
        queue_id: str,
        max_messages: int = 10,
        wait_time: int = 20,
    ) -> list[dict[str, Any]]:
        try:
            client = self._get_client()
            response: dict[str, Any] = client.receive_message(
                QueueUrl=queue_id,
                MaxNumberOfMessages=max_messages,
                WaitTimeSeconds=wait_time,
            )
            messages: list[dict[str, Any]] = [
                {
                    "message_id": msg["MessageId"],
                    "body": msg["Body"],
                    "receipt_handle": msg["ReceiptHandle"],
                }
                for msg in response.get("Messages", [])
            ]
            logger.debug("receive_messages: received %d messages from %s", len(messages), queue_id)
            return messages
        except (ClientError, BotoCoreError) as e:
            logger.error("receive_messages: failed queue=%s error=%s", queue_id, e)
            raise CloudQueueError(f"Failed to receive SQS messages: {e}") from e

    def delete_message(self, queue_id: str, receipt_handle: str) -> None:
        try:
            client = self._get_client()
            client.delete_message(QueueUrl=queue_id, ReceiptHandle=receipt_handle)
            logger.debug("delete_message: success queue=%s", queue_id)
        except (ClientError, BotoCoreError) as e:
            logger.error("delete_message: failed queue=%s error=%s", queue_id, e)
            raise CloudQueueError(f"Failed to delete SQS message: {e}") from e


class AWSQueuePublisher:
    """SQS implementation of QueuePublisher protocol."""

    def _get_client(self) -> Any:
        region: str = str(getattr(settings, "CLOUD_REGION", None) or getattr(settings, "AWS_REGION", "us-east-2"))
        endpoint_url: str | None = os.environ.get("AWS_ENDPOINT_URL") or None
        return boto3.client("sqs", region_name=region, endpoint_url=endpoint_url)

    def send_message(self, queue_id: str, body: str) -> None:
        logger.debug("send_message: queue=%s", queue_id)
        try:
            client = self._get_client()
            client.send_message(QueueUrl=queue_id, MessageBody=body)
            logger.info("send_message: success queue=%s", queue_id)
        except (ClientError, BotoCoreError) as e:
            logger.error("send_message: failed queue=%s error=%s", queue_id, e)
            raise CloudQueueError(f"Failed to send SQS message: {e}") from e
