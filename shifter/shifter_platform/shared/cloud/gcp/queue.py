"""GCP Pub/Sub queue adapters implementing QueueConsumer and QueuePublisher protocols.

Replaces AWS SQS/SNS for event message consumption and publishing.
Provisioner publishes range/NGFW events -> Pub/Sub -> platform consumes.
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

from shared.cloud.exceptions import CloudQueueError

logger = logging.getLogger(__name__)


class GCPQueueConsumer:
    """Pub/Sub pull subscriber implementing QueueConsumer protocol."""

    def _get_client(self):  # type: ignore[no-untyped-def]
        from google.cloud import pubsub_v1  # type: ignore[attr-defined]

        return pubsub_v1.SubscriberClient()

    def _get_project(self) -> str:
        project: str | None = getattr(settings, "GCP_PROJECT_ID", None)
        if not project:
            raise CloudQueueError("GCP_PROJECT_ID setting is required for Pub/Sub")
        return project

    def receive_messages(
        self,
        queue_id: str,
        max_messages: int = 10,
        wait_time: int = 20,
    ) -> list[dict[str, Any]]:
        try:
            client = self._get_client()
            # queue_id can be a full subscription path or short name.
            # Full: projects/my-project/subscriptions/my-sub
            # Short: my-sub (we prepend project)
            if queue_id.startswith("projects/"):
                subscription_path = queue_id
            else:
                project = self._get_project()
                subscription_path = f"projects/{project}/subscriptions/{queue_id}"

            response = client.pull(
                request={
                    "subscription": subscription_path,
                    "max_messages": max_messages,
                },
                timeout=wait_time,
            )
            messages: list[dict[str, Any]] = [
                {
                    "message_id": msg.message.message_id,
                    "body": msg.message.data.decode("utf-8"),
                    "receipt_handle": msg.ack_id,
                }
                for msg in response.received_messages
            ]
            logger.debug(
                "receive_messages: received %d messages from %s",
                len(messages),
                subscription_path,
            )
            return messages
        except Exception as e:
            logger.error("receive_messages: failed queue=%s error=%s", queue_id, e)
            raise CloudQueueError(f"Failed to receive Pub/Sub messages: {e}") from e

    def delete_message(self, queue_id: str, receipt_handle: str) -> None:
        try:
            client = self._get_client()
            if queue_id.startswith("projects/"):
                subscription_path = queue_id
            else:
                project = self._get_project()
                subscription_path = f"projects/{project}/subscriptions/{queue_id}"

            client.acknowledge(
                request={
                    "subscription": subscription_path,
                    "ack_ids": [receipt_handle],
                },
            )
            logger.debug("delete_message: success queue=%s", queue_id)
        except Exception as e:
            logger.error("delete_message: failed queue=%s error=%s", queue_id, e)
            raise CloudQueueError(f"Failed to acknowledge Pub/Sub message: {e}") from e


class GCPQueuePublisher:
    """Pub/Sub publisher implementing QueuePublisher protocol."""

    def _get_client(self):  # type: ignore[no-untyped-def]
        from google.cloud import pubsub_v1  # type: ignore[attr-defined]

        return pubsub_v1.PublisherClient()

    def _get_project(self) -> str:
        project: str | None = getattr(settings, "GCP_PROJECT_ID", None)
        if not project:
            raise CloudQueueError("GCP_PROJECT_ID setting is required for Pub/Sub")
        return project

    def send_message(self, queue_id: str, body: str) -> None:
        logger.debug("send_message: queue=%s", queue_id)
        try:
            client = self._get_client()
            # queue_id can be a full topic path or short name.
            # Full: projects/my-project/topics/my-topic
            # Short: my-topic (we prepend project)
            if queue_id.startswith("projects/"):
                topic_path = queue_id
            else:
                project = self._get_project()
                topic_path = f"projects/{project}/topics/{queue_id}"

            # Encode body as bytes for Pub/Sub.
            data = body.encode("utf-8") if isinstance(body, str) else body
            future = client.publish(topic_path, data)
            # Block until published to ensure delivery.
            future.result()
            logger.info("send_message: success queue=%s", queue_id)
        except Exception as e:
            logger.error("send_message: failed queue=%s error=%s", queue_id, e)
            raise CloudQueueError(f"Failed to publish Pub/Sub message: {e}") from e
