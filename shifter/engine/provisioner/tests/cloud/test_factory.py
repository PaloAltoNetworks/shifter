"""Tests for provisioner cloud abstraction factory functions."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from installation.contract import BackendCapability

import cloud
from cloud import (
    _require_capability,
    get_config_store,
    get_db_auth,
    get_event_bus,
    get_network_inventory,
    get_object_storage,
    get_secrets_store,
)
from cloud.exceptions import CloudProviderNotImplementedError
from cloud.types import ConfigStore, DBAuth, EventBus, NetworkInventory, ObjectStorage, SecretsStore


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

    @patch.dict("os.environ", {"CLOUD_PROVIDER": "aws"})
    def test_get_secrets_store_returns_aws(self):
        store = get_secrets_store()
        assert isinstance(store, SecretsStore)

    @patch.dict("os.environ", {"CLOUD_PROVIDER": "aws"})
    def test_get_network_inventory_returns_aws(self):
        inventory = get_network_inventory()
        assert isinstance(inventory, NetworkInventory)


class TestFactoryWithGCP:
    """Factory returns GCP adapters when CLOUD_PROVIDER=gcp."""

    @patch.dict("os.environ", {"CLOUD_PROVIDER": "gcp"})
    def test_get_event_bus_returns_gcp(self):
        bus = get_event_bus()
        assert isinstance(bus, EventBus)

    @patch.dict("os.environ", {"CLOUD_PROVIDER": "gcp"})
    def test_get_config_store_returns_gcp(self):
        store = get_config_store()
        assert isinstance(store, ConfigStore)

    @patch.dict("os.environ", {"CLOUD_PROVIDER": "gcp"})
    def test_get_db_auth_returns_gcp(self):
        auth = get_db_auth()
        assert isinstance(auth, DBAuth)

    @patch.dict("os.environ", {"CLOUD_PROVIDER": "gcp"})
    def test_get_object_storage_returns_gcp(self):
        storage = get_object_storage()
        assert isinstance(storage, ObjectStorage)

    @patch.dict("os.environ", {"CLOUD_PROVIDER": "gcp"})
    def test_get_secrets_store_returns_gcp(self):
        store = get_secrets_store()
        assert isinstance(store, SecretsStore)

    @patch.dict("os.environ", {"CLOUD_PROVIDER": "gcp"})
    def test_get_network_inventory_returns_gcp(self):
        inventory = get_network_inventory()
        assert isinstance(inventory, NetworkInventory)


class TestFactoryWithUnsupportedProvider:
    """Factory raises clear error for unsupported providers."""

    @patch.dict("os.environ", {"CLOUD_PROVIDER": "azure"})
    def test_raises_for_unknown_provider(self):
        with pytest.raises(CloudProviderNotImplementedError, match="azure"):
            get_network_inventory()


class TestFactoryDefaultProvider:
    """Factory defaults to aws when CLOUD_PROVIDER not set."""

    @patch.dict("os.environ", {}, clear=False)
    def test_defaults_to_aws(self):
        # Remove CLOUD_PROVIDER if present
        import os

        os.environ.pop("CLOUD_PROVIDER", None)
        bus = get_event_bus()
        assert isinstance(bus, EventBus)


class TestRequireCapability:
    """``_require_capability`` is defense-in-depth alongside resolve_cloud_provider's
    identity check: a *registered* backend that has not claimed a capability, or
    whose bundle cannot be found at all, must still fail closed rather than let a
    factory fall through to another provider's adapter."""

    @patch.dict("os.environ", {"CLOUD_PROVIDER": "aws"})
    def test_missing_bundle_for_a_known_identity_raises(self, monkeypatch):
        """Registry drift (bundle missing despite a resolvable identity) fails closed."""
        monkeypatch.setattr(cloud, "get_backend_bundle", lambda name: None)

        with pytest.raises(CloudProviderNotImplementedError, match="aws") as excinfo:
            _require_capability(BackendCapability.EVENT_BUS)
        assert excinfo.value.capability is BackendCapability.EVENT_BUS

    @patch.dict("os.environ", {"CLOUD_PROVIDER": "aws"})
    def test_registered_backend_missing_capability_raises(self, monkeypatch):
        fake_bundle = SimpleNamespace(capabilities=frozenset({BackendCapability.STORAGE}))
        monkeypatch.setattr(cloud, "get_backend_bundle", lambda name: fake_bundle)

        with pytest.raises(CloudProviderNotImplementedError, match="EVENT_BUS"):
            _require_capability(BackendCapability.EVENT_BUS)

    @patch.dict("os.environ", {"CLOUD_PROVIDER": "aws"})
    def test_registered_backend_with_capability_returns_provider(self, monkeypatch):
        fake_bundle = SimpleNamespace(capabilities=frozenset({BackendCapability.EVENT_BUS}))
        monkeypatch.setattr(cloud, "get_backend_bundle", lambda name: fake_bundle)

        assert _require_capability(BackendCapability.EVENT_BUS) == "aws"

    @patch.dict("os.environ", {"CLOUD_PROVIDER": "azure"})
    def test_unresolvable_identity_raises_before_capability_check(self):
        """An identity resolve_cloud_provider already rejects fails closed at the
        identity check -- observably, the error carries no capability (the capability
        lookup is never reached)."""
        with pytest.raises(CloudProviderNotImplementedError, match="azure") as excinfo:
            _require_capability(BackendCapability.EVENT_BUS)
        assert excinfo.value.capability is None
