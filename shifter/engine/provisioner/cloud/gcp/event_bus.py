"""Google Pub/Sub adapter implementing EventBus protocol."""

from __future__ import annotations

import logging

from cloud.exceptions import CloudEventBusError
from cloud.gcp.base import build_topic_path, import_google_module

logger = logging.getLogger(__name__)


class GCPEventBus:
    """Pub/Sub implementation of EventBus protocol."""

    def publish(
        self,
        topic_id: str,
        message: str,
        attributes: dict[str, str] | None = None,
    ) -> None:
        logger.debug("publish: topic_id=%s", topic_id)
        try:
            pubsub = import_google_module("google.cloud.pubsub_v1")
            client = pubsub.PublisherClient()
            topic = build_topic_path(topic_id, client)
            client.publish(topic, message.encode("utf-8"), **(attributes or {})).result(timeout=30)
        except ImportError as e:
            raise CloudEventBusError("GCP event bus support requires google-cloud-pubsub") from e
        except Exception as e:
            logger.error("publish: failed topic_id=%s error=%s", topic_id, e)
            raise CloudEventBusError(f"Failed to publish Pub/Sub event: {e}") from e
