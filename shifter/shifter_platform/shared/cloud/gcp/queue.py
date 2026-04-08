"""GCP Pub/Sub queue adapters (stubs).

Will replace AWS SQS for event message consumption and publishing.
Provisioner publishes range/NGFW events → Pub/Sub → platform consumes.
"""

from __future__ import annotations

from typing import Any

from shared.cloud.exceptions import CloudProviderNotImplementedError


class GCPQueueConsumer:
    """Pub/Sub pull subscriber — stub, not yet implemented."""

    def receive_messages(self, queue_id: str, max_messages: int = 10, wait_time: int = 20) -> list[dict[str, Any]]:
        raise CloudProviderNotImplementedError("gcp")

    def delete_message(self, queue_id: str, receipt_handle: str) -> None:
        raise CloudProviderNotImplementedError("gcp")


class GCPQueuePublisher:
    """Pub/Sub publisher — stub, not yet implemented."""

    def send_message(self, queue_id: str, body: str) -> None:
        raise CloudProviderNotImplementedError("gcp")
