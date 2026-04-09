"""Tests for cloud abstraction factory functions."""

import pytest

from shared.cloud import (
    get_object_storage,
    get_queue_consumer,
    get_queue_publisher,
    get_secrets_store,
    get_task_runner,
)
from shared.cloud.exceptions import CloudProviderNotImplementedError
from shared.cloud.types import (
    ObjectStorage,
    QueueConsumer,
    QueuePublisher,
    SecretsStore,
    TaskRunner,
)


class TestFactoryWithAWS:
    """Factory returns AWS adapters when CLOUD_PROVIDER=aws."""

    def test_get_object_storage_returns_aws(self, settings):
        settings.CLOUD_PROVIDER = "aws"
        storage = get_object_storage()
        assert isinstance(storage, ObjectStorage)

    def test_get_task_runner_returns_aws(self, settings):
        settings.CLOUD_PROVIDER = "aws"
        runner = get_task_runner()
        assert isinstance(runner, TaskRunner)

    def test_get_queue_consumer_returns_aws(self, settings):
        settings.CLOUD_PROVIDER = "aws"
        consumer = get_queue_consumer()
        assert isinstance(consumer, QueueConsumer)

    def test_get_queue_publisher_returns_aws(self, settings):
        settings.CLOUD_PROVIDER = "aws"
        publisher = get_queue_publisher()
        assert isinstance(publisher, QueuePublisher)

    def test_get_secrets_store_returns_aws(self, settings):
        settings.CLOUD_PROVIDER = "aws"
        store = get_secrets_store()
        assert isinstance(store, SecretsStore)


class TestFactoryWithGCP:
    """Factory returns GCP adapters when CLOUD_PROVIDER=gcp."""

    def test_get_object_storage_returns_gcp(self, settings):
        settings.CLOUD_PROVIDER = "gcp"
        storage = get_object_storage()
        assert isinstance(storage, ObjectStorage)

    def test_get_task_runner_returns_gcp(self, settings):
        settings.CLOUD_PROVIDER = "gcp"
        runner = get_task_runner()
        assert isinstance(runner, TaskRunner)

    def test_get_queue_consumer_returns_gcp(self, settings):
        settings.CLOUD_PROVIDER = "gcp"
        consumer = get_queue_consumer()
        assert isinstance(consumer, QueueConsumer)

    def test_get_queue_publisher_returns_gcp(self, settings):
        settings.CLOUD_PROVIDER = "gcp"
        publisher = get_queue_publisher()
        assert isinstance(publisher, QueuePublisher)

    def test_get_secrets_store_returns_gcp(self, settings):
        settings.CLOUD_PROVIDER = "gcp"
        store = get_secrets_store()
        assert isinstance(store, SecretsStore)


class TestFactoryWithUnsupportedProvider:
    """Factory raises clear error for unsupported providers."""

    def test_get_object_storage_raises_for_unknown(self, settings):
        settings.CLOUD_PROVIDER = "azure"
        with pytest.raises(CloudProviderNotImplementedError, match="azure"):
            get_object_storage()


class TestFactoryDefaultProvider:
    """Factory defaults to aws when CLOUD_PROVIDER not set."""

    def test_defaults_to_aws(self, settings):
        settings.CLOUD_PROVIDER = "aws"
        # Should not raise
        storage = get_object_storage()
        assert isinstance(storage, ObjectStorage)
