"""Cloud provider abstraction layer.

Factory functions that return provider-specific implementations based on
the CLOUD_PROVIDER Django setting. Defaults to "aws".

Usage:
    from shared.cloud import get_object_storage, get_task_runner
    storage = get_object_storage()
    runner = get_task_runner()
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings

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
        ObjectStorage,
        QueueConsumer,
        QueuePublisher,
        SecretsStore,
        TaskRunner,
    )


def _get_provider() -> str:
    return getattr(settings, "CLOUD_PROVIDER", "aws")


def get_object_storage() -> ObjectStorage:
    """Return an ObjectStorage implementation for the configured provider."""
    provider = _get_provider()
    if provider == "aws":
        from shared.cloud.aws.storage import AWSObjectStorage

        return AWSObjectStorage()
    if provider == "gcp":
        from shared.cloud.gcp.storage import GCPObjectStorage

        return GCPObjectStorage()
    raise CloudProviderNotImplementedError(provider)


def get_task_runner() -> TaskRunner:
    """Return a TaskRunner implementation for the configured provider."""
    provider = _get_provider()
    if provider == "aws":
        from shared.cloud.aws.task_runner import AWSTaskRunner

        return AWSTaskRunner()
    if provider == "gcp":
        from shared.cloud.gcp.task_runner import GCPTaskRunner

        return GCPTaskRunner()
    raise CloudProviderNotImplementedError(provider)


def get_queue_consumer() -> QueueConsumer:
    """Return a QueueConsumer implementation for the configured provider."""
    provider = _get_provider()
    if provider == "aws":
        from shared.cloud.aws.queue import AWSQueueConsumer

        return AWSQueueConsumer()
    if provider == "gcp":
        from shared.cloud.gcp.queue import GCPQueueConsumer

        return GCPQueueConsumer()
    raise CloudProviderNotImplementedError(provider)


def get_queue_publisher() -> QueuePublisher:
    """Return a QueuePublisher implementation for the configured provider."""
    provider = _get_provider()
    if provider == "aws":
        from shared.cloud.aws.queue import AWSQueuePublisher

        return AWSQueuePublisher()
    if provider == "gcp":
        from shared.cloud.gcp.queue import GCPQueuePublisher

        return GCPQueuePublisher()
    raise CloudProviderNotImplementedError(provider)


def get_secrets_store() -> SecretsStore:
    """Return a SecretsStore implementation for the configured provider."""
    provider = _get_provider()
    if provider == "aws":
        from shared.cloud.aws.secrets import AWSSecretsStore

        return AWSSecretsStore()
    if provider == "gcp":
        from shared.cloud.gcp.secrets import GCPSecretsStore

        return GCPSecretsStore()
    raise CloudProviderNotImplementedError(provider)
