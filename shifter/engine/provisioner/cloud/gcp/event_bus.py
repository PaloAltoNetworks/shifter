"""GCP Pub/Sub event bus adapter (stub).

Will replace AWS SNS for event publishing.
"""

from __future__ import annotations

from cloud.exceptions import CloudProviderNotImplementedError

from .base import BaseGCPAdapter


class GCPEventBus(BaseGCPAdapter):
    """Pub/Sub event bus — stub, not yet implemented."""

    def publish(
        self,
        topic_id: str,
        message: str,
        attributes: dict[str, str] | None = None,
    ) -> None:
        raise CloudProviderNotImplementedError("gcp", "EventBus")
