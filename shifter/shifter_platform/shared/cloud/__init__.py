"""Cloud provider abstraction layer.

Factory functions that return provider-specific implementations based on the
``CLOUD_PROVIDER`` Django setting. That setting is resolved and validated once at
the Django composition root (``config._cloud.resolve_cloud_provider``) against the
``installation`` registry, so every factory below consumes one validated backend
selection rather than re-reading the environment with an implicit ``aws`` default
(PLAT-2005). Each factory also validates that the selected backend declares the
capability it needs before constructing an adapter, and fails closed otherwise.

Usage:
    from shared.cloud import get_object_storage, get_task_runner
    storage = get_object_storage()
    runner = get_task_runner()
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from installation.contract import BackendCapability
from installation.registry import get_backend_bundle

from shared.cloud.exceptions import CloudProviderNotImplementedError

# Cross-provider container-name contract for the engine provisioner Job.
# Lives at the cloud-neutral layer so AWS/ECS dispatch sites and the GCP
# task-runner gate import the same string. The GCP runner uses this to
# select issue #1103 hardening (readOnlyRootFilesystem, writable mounts,
# fsGroup); the ECS task definition's container_name must also match it
# so behavior is consistent across providers — a structural test in
# `tests/shared/cloud/test_gcp_task_runner.py` enforces alignment.
PROVISIONER_CONTAINER_NAME = "pulumi-provisioner"

if TYPE_CHECKING:
    from shared.cloud.types import (
        EventBus,
        ObjectStorage,
        QueueConsumer,
        QueuePublisher,
        SecretsStore,
        TaskRunner,
    )


def _get_provider() -> str:
    return settings.CLOUD_PROVIDER


def _require_capability(capability: BackendCapability) -> str:
    """Return the validated active backend, failing closed when it does not
    declare ``capability`` in the installation registry (PLAT-2005)."""
    provider = _get_provider()
    bundle = get_backend_bundle(provider)
    if bundle is None or capability not in bundle.capabilities:
        raise CloudProviderNotImplementedError(provider, capability)
    return provider


def get_object_storage() -> ObjectStorage:
    """Return an ObjectStorage implementation for the configured provider."""
    provider = _require_capability(BackendCapability.STORAGE)
    if provider == "aws":
        from shared.cloud.aws.storage import AWSObjectStorage

        return AWSObjectStorage()
    if provider == "gcp":
        from shared.cloud.gcp.storage import GCPObjectStorage

        return GCPObjectStorage()
    raise CloudProviderNotImplementedError(provider, BackendCapability.STORAGE)


def get_task_runner() -> TaskRunner:
    """Return a TaskRunner implementation for the configured provider."""
    provider = _require_capability(BackendCapability.TASK_RUNNER)
    if provider == "aws":
        from shared.cloud.aws.task_runner import AWSTaskRunner

        return AWSTaskRunner()
    if provider == "gcp":
        from shared.cloud.gcp.task_runner import GCPTaskRunner

        return GCPTaskRunner()
    raise CloudProviderNotImplementedError(provider, BackendCapability.TASK_RUNNER)


def get_queue_consumer() -> QueueConsumer:
    """Return a QueueConsumer implementation for the configured provider."""
    provider = _require_capability(BackendCapability.QUEUE_CONSUMER)
    if provider == "aws":
        from shared.cloud.aws.queue import AWSQueueConsumer

        return AWSQueueConsumer()
    if provider == "gcp":
        from shared.cloud.gcp.queue import GCPQueueConsumer

        return GCPQueueConsumer()
    raise CloudProviderNotImplementedError(provider, BackendCapability.QUEUE_CONSUMER)


def get_queue_publisher() -> QueuePublisher:
    """Return a QueuePublisher implementation for the configured provider."""
    provider = _require_capability(BackendCapability.QUEUE_PUBLISHER)
    if provider == "aws":
        from shared.cloud.aws.queue import AWSQueuePublisher

        return AWSQueuePublisher()
    if provider == "gcp":
        from shared.cloud.gcp.queue import GCPQueuePublisher

        return GCPQueuePublisher()
    raise CloudProviderNotImplementedError(provider, BackendCapability.QUEUE_PUBLISHER)


def get_secrets_store() -> SecretsStore:
    """Return a SecretsStore implementation for the configured provider."""
    provider = _require_capability(BackendCapability.SECRETS)
    if provider == "aws":
        from shared.cloud.aws.secrets import AWSSecretsStore

        return AWSSecretsStore()
    if provider == "gcp":
        from shared.cloud.gcp.secrets import GCPSecretsStore

        return GCPSecretsStore()
    raise CloudProviderNotImplementedError(provider, BackendCapability.SECRETS)


def get_event_bus() -> EventBus:
    """Return an EventBus implementation for the configured provider."""
    provider = _require_capability(BackendCapability.EVENT_BUS)
    if provider == "aws":
        from shared.cloud.aws.event_bus import AWSEventBus

        return AWSEventBus()
    if provider == "gcp":
        from shared.cloud.gcp.event_bus import GCPEventBus

        return GCPEventBus()
    raise CloudProviderNotImplementedError(provider, BackendCapability.EVENT_BUS)
