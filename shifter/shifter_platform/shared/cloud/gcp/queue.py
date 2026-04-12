"""Google Pub/Sub adapters implementing QueueConsumer and QueuePublisher."""

from __future__ import annotations

import logging

from shared.cloud.exceptions import CloudQueueError
from shared.cloud.gcp.base import build_subscription_path, build_topic_path, import_google_module

logger = logging.getLogger(__name__)
_PUBSUB_MODULE = "google.cloud.pubsub_v1"
_PUBSUB_IMPORT_ERROR = "GCP queue support requires google-cloud-pubsub"


class GCPQueueConsumer:
    """Pub/Sub subscription consumer implementation of QueueConsumer."""

    def receive_messages(
        self,
        queue_id: str,
        max_messages: int = 10,
        wait_time: int = 20,
    ) -> list[dict]:
        try:
            pubsub = import_google_module(_PUBSUB_MODULE)
            client = pubsub.SubscriberClient()
            subscription = build_subscription_path(queue_id, client)
            response = client.pull(
                request={"subscription": subscription, "max_messages": max_messages},
                timeout=wait_time,
            )
            return [
                {
                    "message_id": msg.message.message_id,
                    "body": msg.message.data.decode("utf-8"),
                    "receipt_handle": msg.ack_id,
                }
                for msg in response.received_messages
            ]
        except ImportError as e:
            raise CloudQueueError(_PUBSUB_IMPORT_ERROR) from e
        except Exception as e:
            if e.__class__.__name__ == "DeadlineExceeded":
                return []
            logger.error("receive_messages: failed queue=%s error=%s", queue_id, e)
            raise CloudQueueError(f"Failed to receive Pub/Sub messages: {e}") from e

    def delete_message(self, queue_id: str, receipt_handle: str) -> None:
        try:
            pubsub = import_google_module(_PUBSUB_MODULE)
            client = pubsub.SubscriberClient()
            subscription = build_subscription_path(queue_id, client)
            client.acknowledge(request={"subscription": subscription, "ack_ids": [receipt_handle]})
        except ImportError as e:
            raise CloudQueueError(_PUBSUB_IMPORT_ERROR) from e
        except Exception as e:
            logger.error("delete_message: failed queue=%s error=%s", queue_id, e)
            raise CloudQueueError(f"Failed to ack Pub/Sub message: {e}") from e


class GCPQueuePublisher:
    """Pub/Sub topic publisher implementation of QueuePublisher."""

    def send_message(self, queue_id: str, body: str) -> None:
        logger.debug("send_message: queue=%s", queue_id)
        try:
            pubsub = import_google_module(_PUBSUB_MODULE)
            client = pubsub.PublisherClient()
            topic = build_topic_path(queue_id, client)
            client.publish(topic, body.encode("utf-8")).result(timeout=30)
        except ImportError as e:
            raise CloudQueueError(_PUBSUB_IMPORT_ERROR) from e
        except Exception as e:
            logger.error("send_message: failed queue=%s error=%s", queue_id, e)
            raise CloudQueueError(f"Failed to publish Pub/Sub message: {e}") from e
