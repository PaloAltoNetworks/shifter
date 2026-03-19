"""Tests for provisioner cloud abstraction factory functions."""

from unittest.mock import patch

import pytest

from cloud import get_config_store, get_db_auth, get_event_bus, get_object_storage
from cloud.exceptions import CloudProviderNotImplementedError
from cloud.types import ConfigStore, DBAuth, EventBus, ObjectStorage


class TestFactoryWithAWS:
    """Factory returns AWS adapters when CLOUD_PROVIDER=aws."""

    @patch.dict("os.environ", {"CLOUD_PROVIDER": "aws"})
    def test_get_event_bus_returns_aws(self):
        bus = get_event_bus()
        assert isinstance(bus, EventBus)

    @patch.dict("os.environ", {"CLOUD_PROVIDER": "aws"})
    def test_get_config_store_returns_aws(self):
        store = get_config_store()
        assert isinstance(store, ConfigStore)

    @patch.dict("os.environ", {"CLOUD_PROVIDER": "aws"})
    def test_get_db_auth_returns_aws(self):
        auth = get_db_auth()
        assert isinstance(auth, DBAuth)

    @patch.dict("os.environ", {"CLOUD_PROVIDER": "aws"})
    def test_get_object_storage_returns_aws(self):
        storage = get_object_storage()
        assert isinstance(storage, ObjectStorage)


class TestFactoryWithUnsupportedProvider:
    """Factory raises clear error for unsupported providers."""

    @patch.dict("os.environ", {"CLOUD_PROVIDER": "gcp"})
    def test_get_event_bus_raises_for_gcp(self):
        with pytest.raises(CloudProviderNotImplementedError, match="gcp"):
            get_event_bus()

    @patch.dict("os.environ", {"CLOUD_PROVIDER": "gcp"})
    def test_get_config_store_raises_for_gcp(self):
        with pytest.raises(CloudProviderNotImplementedError, match="gcp"):
            get_config_store()

    @patch.dict("os.environ", {"CLOUD_PROVIDER": "gcp"})
    def test_get_db_auth_raises_for_gcp(self):
        with pytest.raises(CloudProviderNotImplementedError, match="gcp"):
            get_db_auth()

    @patch.dict("os.environ", {"CLOUD_PROVIDER": "azure"})
    def test_raises_for_unknown_provider(self):
        with pytest.raises(CloudProviderNotImplementedError, match="azure"):
            get_object_storage()


class TestFactoryDefaultProvider:
    """Factory defaults to aws when CLOUD_PROVIDER not set."""

    @patch.dict("os.environ", {}, clear=False)
    def test_defaults_to_aws(self):
        # Remove CLOUD_PROVIDER if present
        import os

        os.environ.pop("CLOUD_PROVIDER", None)
        bus = get_event_bus()
        assert isinstance(bus, EventBus)
