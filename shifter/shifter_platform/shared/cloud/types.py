"""Cloud provider protocol definitions.

These protocols define the interface that each cloud provider adapter must
implement. They use structural subtyping (PEP 544) — any class with the
right methods satisfies the protocol, no explicit inheritance required.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from shared.capacity import CapacityMetricSpec, ObservationResult, PartitionRef


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

    def download_object(
        self,
        bucket: str,
        key: str,
        dest_path: str,
        *,
        max_bytes: int,
        expected_identity: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Download a full object to ``dest_path``, bounded by ``max_bytes``.

        When ``expected_identity`` (as returned by :meth:`head_object`, carrying
        provider-specific ``etag`` / ``generation``) is supplied, the download is
        bound to that exact object version so an object replaced after validation
        fails closed with ``ObjectPreconditionError`` (defeats a
        head-then-download TOCTOU). Raises ``CloudStorageError`` when the object
        exceeds ``max_bytes`` or on any other failure, and ``ValueError`` when
        ``max_bytes`` is not positive. Returns the realized object identity
        (always ``content_length`` and ``etag``; providers may add ``generation``).
        """
        ...

    def generate_presigned_upload_url(
        self,
        bucket: str,
        key: str,
        content_type: str,
        expires_in: int,
        content_length: int | None = None,
    ) -> str:
        """Presign a single-object PUT.

        When ``content_length`` is given the adapter binds the exact byte length
        into its signed request where the provider reliably enforces it, so an
        oversized transfer fails at the storage layer. This is defense in depth
        only; it never replaces the server-side finalization size check.
        """
        ...

    def generate_presigned_download_url(
        self,
        bucket: str,
        key: str,
        expires_in: int,
    ) -> str: ...

    def tag_object(self, bucket: str, key: str, tags: dict[str, str]) -> None: ...


class TaskInterruptDisposition:
    """Idempotent control outcome of ``TaskRunner.interrupt_task`` (#277).

    A task-control disposition only -- never range lifecycle success. The launcher
    worker maps these onto the durable ``InterruptState`` and decides when the
    canonical destroy may be enqueued (only on ``TERMINAL_ABSENT``).
    """

    #: Stop issued; the workload is not yet observed absent (poll again).
    STOPPING = "stopping"
    #: The task is gone / already terminal -- safe to converge to destroy.
    TERMINAL_ABSENT = "terminal_absent"
    #: The observed workload is not the reserved intent -- fail closed, do not stop it.
    IDENTITY_MISMATCH = "identity_mismatch"
    #: Provider outcome unknown -- reconcile by trusted identity before retrying.
    UNKNOWN = "unknown"


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
        task_identity: str | None = None,
    ) -> str | None: ...

    def get_task_status(self, cluster: str, task_id: str) -> dict[str, Any] | None: ...

    def interrupt_task(
        self,
        cluster: str,
        task_ref: str,
        expected_identity: dict[str, Any],
        grace_seconds: int | None = None,
    ) -> str:
        """Verify the workload is the reserved intent, then stop it (#277).

        Reads and verifies the provider object against ``expected_identity``
        before any mutation, then requests termination. Returns a
        ``TaskInterruptDisposition`` value; it never returns range success.
        """
        ...


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


@runtime_checkable
class CapacityInventory(Protocol):
    """Protocol for read-only capacity observation (Service Quotas, Cloud Monitoring, etc.).

    Implementations answer "what is the limit and current usage for this metric
    in this partition" and never mutate provider state. They degrade rather than
    raise: an unreachable provider, a malformed payload, or a metric with no
    adapter mapping returns an :class:`~shared.capacity.ObservationResult` whose
    ``observation`` is ``None`` and whose ``reason_code`` says why, so the
    pre-spinup path cannot be broken by a capacity read.
    """

    def observe(self, spec: CapacityMetricSpec, partition: PartitionRef) -> ObservationResult: ...
