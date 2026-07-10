"""Cloud provider protocol definitions.

These protocols define the interface that each cloud provider adapter must
implement. They use structural subtyping (PEP 544) — any class with the
right methods satisfies the protocol, no explicit inheritance required.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ObjectStorage(Protocol):
    """Protocol for object storage operations (S3, GCS, etc.)."""

    def upload_file(
        self,
        file_obj: Any,
        bucket: str,
        key: str,
        content_type: str = "",
    ) -> None: ...

    def delete_object(self, bucket: str, key: str) -> None: ...

    def copy_object(self, bucket: str, src_key: str, dst_key: str) -> None: ...

    def copy_object_conditional(
        self,
        bucket: str,
        src_key: str,
        dst_key: str,
        *,
        expected_identity: dict[str, Any],
    ) -> None:
        """Copy ``src_key`` to ``dst_key`` only if the source still matches
        ``expected_identity`` and the destination does not already exist.

        ``expected_identity`` is an opaque object-identity mapping as returned by
        :meth:`head_object` (provider-specific keys such as ``etag`` and
        ``generation``); the adapter selects the appropriate provider
        precondition. Raises ``ObjectPreconditionError`` when the precondition
        fails (source changed or destination present) and ``CloudStorageError``
        for any other failure. Fails closed if the identity lacks the field the
        provider needs.
        """
        ...

    def object_exists(self, bucket: str, key: str) -> bool: ...

    def head_object(self, bucket: str, key: str) -> dict[str, Any]:
        """Return object metadata/identity.

        Always includes ``content_length`` and ``etag``. Providers may include
        additional identity fields (for example GCS ``generation``) used as the
        strongest available precondition by :meth:`copy_object_conditional`.
        """
        ...

    def read_object_header(self, bucket: str, key: str, max_bytes: int) -> bytes: ...

    def generate_presigned_upload_url(
        self,
        bucket: str,
        key: str,
        content_type: str,
        expires_in: int,
    ) -> str: ...

    def generate_presigned_download_url(
        self,
        bucket: str,
        key: str,
        expires_in: int,
    ) -> str: ...

    def tag_object(self, bucket: str, key: str, tags: dict[str, str]) -> None: ...


@runtime_checkable
class TaskRunner(Protocol):
    """Protocol for container/task orchestration (ECS, Kubernetes Jobs, etc.)."""

    def run_task(
        self,
        task_definition: str,
        cluster: str,
        command: list[str],
        container_name: str,
        env_overrides: dict[str, str] | None = None,
        network_config: dict[str, Any] | None = None,
    ) -> str | None: ...

    def get_task_status(self, cluster: str, task_id: str) -> dict[str, Any] | None: ...


@runtime_checkable
class QueueConsumer(Protocol):
    """Protocol for consuming messages from a queue (SQS, Pub/Sub, etc.)."""

    def receive_messages(
        self,
        queue_id: str,
        max_messages: int = 10,
        wait_time: int = 20,
    ) -> list[dict[str, Any]]: ...

    def delete_message(self, queue_id: str, receipt_handle: str) -> None: ...


@runtime_checkable
class QueuePublisher(Protocol):
    """Protocol for publishing messages to a queue (SQS, Pub/Sub, etc.)."""

    def send_message(self, queue_id: str, body: str) -> None: ...


@runtime_checkable
class SecretsStore(Protocol):
    """Protocol for secrets retrieval (Secrets Manager, Secret Manager, etc.)."""

    def get_secret(self, secret_id: str) -> str: ...


@runtime_checkable
class EventBus(Protocol):
    """Protocol for publishing events to a topic (SNS, Pub/Sub, etc.)."""

    def publish(
        self,
        topic_id: str,
        message: str,
        attributes: dict[str, str] | None = None,
    ) -> None: ...
