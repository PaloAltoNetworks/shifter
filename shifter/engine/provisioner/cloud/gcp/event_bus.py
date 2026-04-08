"""GCP Pub/Sub event bus adapter implementing EventBus protocol."""

from __future__ import annotations

import logging

from cloud.exceptions import CloudEventBusError

from .base import BaseGCPAdapter

logger = logging.getLogger(__name__)


class GCPEventBus(BaseGCPAdapter):
    """Pub/Sub implementation of EventBus protocol."""

    def _get_client(self):  # type: ignore[no-untyped-def]
        from google.cloud import pubsub_v1  # type: ignore[attr-defined]

        return pubsub_v1.PublisherClient()

    def publish(
        self,
        topic_id: str,
        message: str,
        attributes: dict[str, str] | None = None,
    ) -> None:
        logger.debug("publish: topic_id=%s", topic_id)
        try:
            client = self._get_client()
            # Support both full topic paths and short names.
            if topic_id.startswith("projects/"):
                topic_path = topic_id
            else:
                project = self._get_project()
                topic_path = f"projects/{project}/topics/{topic_id}"

            data = message.encode("utf-8") if isinstance(message, str) else message
            kwargs = {"data": data}
            if attributes:
                kwargs.update(attributes)

            future = client.publish(topic_path, **kwargs)
            future.result()  # Block until published
            logger.info("publish: success topic_id=%s", topic_id)
        except Exception as e:
            logger.error("publish: failed topic_id=%s error=%s", topic_id, e)
            raise CloudEventBusError(f"Failed to publish to Pub/Sub: {e}") from e
