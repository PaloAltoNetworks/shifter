"""Google Pub/Sub adapter implementing EventBus protocol."""

from __future__ import annotations

import logging

from shared.cloud.exceptions import CloudEventBusError
from shared.cloud.gcp.base import build_topic_path, import_google_module

logger = logging.getLogger(__name__)

_PUBSUB_MODULE = "google.cloud.pubsub_v1"
_PUBSUB_IMPORT_ERROR = "GCP event bus support requires google-cloud-pubsub"


class GCPEventBus:
    """Pub/Sub implementation of EventBus protocol."""

    @staticmethod
    def publish(
        topic_id: str,
        message: str,
        attributes: dict[str, str] | None = None,
    ) -> None:
        logger.debug("publish: topic_id=%s", topic_id)
        try:
            pubsub = import_google_module(_PUBSUB_MODULE)
            client = pubsub.PublisherClient()
            topic = build_topic_path(topic_id, client)
            client.publish(topic, message.encode("utf-8"), **(attributes or {})).result(timeout=30)
            logger.info("publish: success topic_id=%s", topic_id)
        except ImportError as e:
            raise CloudEventBusError(_PUBSUB_IMPORT_ERROR) from e
        except Exception as e:
            logger.exception("publish: failed topic_id=%s error=%s", topic_id, e)
            raise CloudEventBusError(f"Failed to publish Pub/Sub event: {e}") from e
