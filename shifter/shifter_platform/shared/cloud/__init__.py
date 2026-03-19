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
    raise CloudProviderNotImplementedError(provider)


def get_task_runner() -> TaskRunner:
    """Return a TaskRunner implementation for the configured provider."""
    provider = _get_provider()
    if provider == "aws":
        from shared.cloud.aws.task_runner import AWSTaskRunner

        return AWSTaskRunner()
    raise CloudProviderNotImplementedError(provider)


def get_queue_consumer() -> QueueConsumer:
    """Return a QueueConsumer implementation for the configured provider."""
    provider = _get_provider()
    if provider == "aws":
        from shared.cloud.aws.queue import AWSQueueConsumer

        return AWSQueueConsumer()
    raise CloudProviderNotImplementedError(provider)


def get_queue_publisher() -> QueuePublisher:
    """Return a QueuePublisher implementation for the configured provider."""
    provider = _get_provider()
    if provider == "aws":
        from shared.cloud.aws.queue import AWSQueuePublisher

        return AWSQueuePublisher()
    raise CloudProviderNotImplementedError(provider)


def get_secrets_store() -> SecretsStore:
    """Return a SecretsStore implementation for the configured provider."""
    provider = _get_provider()
    if provider == "aws":
        from shared.cloud.aws.secrets import AWSSecretsStore

        return AWSSecretsStore()
    raise CloudProviderNotImplementedError(provider)
