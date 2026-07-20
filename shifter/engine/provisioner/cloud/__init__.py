"""Cloud provider abstraction layer for the provisioner.

Factory functions that return provider-specific implementations for the
active cloud backend. The backend identity is resolved once via
``config.resolve_cloud_provider`` (PLAT-2005), which validates it against
the ``installation`` registry -- the single source of truth for supported
backends (docs/architecture/root-configured-backend-bundles.md) -- instead
of each factory re-reading ``CLOUD_PROVIDER`` with its own implicit "aws"
default.

This module has no Django dependency.

Usage:
    from cloud import get_event_bus, get_config_store, get_db_auth, get_secrets_store
    bus = get_event_bus()
    store = get_config_store()
    auth = get_db_auth()
    secrets = get_secrets_store()
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from installation.registry import get_backend_bundle

from cloud.exceptions import CloudProviderNotImplementedError
from config import resolve_cloud_provider

if TYPE_CHECKING:
    from installation.contract import BackendCapability

    from cloud.types import ConfigStore, DBAuth, EventBus, NetworkInventory, ObjectStorage, SecretsStore


def _get_provider() -> str:
    return resolve_cloud_provider()


def _require_capability(capability: BackendCapability) -> str:
    """Resolve the active provider and fail closed if it lacks ``capability``.

    Defense-in-depth alongside ``resolve_cloud_provider``'s identity check
    (docs/architecture/root-configured-backend-bundles.md, "Whole-repository
    and extensibility guardrails"): a registered backend that has not (yet)
    claimed a capability a factory needs must fail rather than fall through
    to another provider's adapter.
    """
    provider = _get_provider()
    bundle = get_backend_bundle(provider)
    if bundle is None or capability not in bundle.capabilities:
        raise CloudProviderNotImplementedError(provider, capability)
    return provider


def get_event_bus() -> EventBus:
    """Return an EventBus implementation for the configured provider."""
    from installation.contract import BackendCapability

    provider = _require_capability(BackendCapability.EVENT_BUS)
    if provider == "aws":
        from cloud.aws.event_bus import AWSEventBus

        return AWSEventBus()
    if provider == "gcp":
        from cloud.gcp.event_bus import GCPEventBus

        return GCPEventBus()
    raise CloudProviderNotImplementedError(provider, BackendCapability.EVENT_BUS)


def get_config_store() -> ConfigStore:
    """Return a ConfigStore implementation for the configured provider."""
    from installation.contract import BackendCapability

    provider = _require_capability(BackendCapability.CONFIG_STORE)
    if provider == "aws":
        from cloud.aws.config_store import AWSConfigStore

        return AWSConfigStore()
    if provider == "gcp":
        from cloud.gcp.config_store import GCPConfigStore

        return GCPConfigStore()
    raise CloudProviderNotImplementedError(provider, BackendCapability.CONFIG_STORE)


def get_db_auth() -> DBAuth:
    """Return a DBAuth implementation for the configured provider."""
    from installation.contract import BackendCapability

    provider = _require_capability(BackendCapability.DATABASE_AUTH)
    if provider == "aws":
        from cloud.aws.db_auth import AWSDBAuth

        return AWSDBAuth()
    if provider == "gcp":
        from cloud.gcp.db_auth import GCPDBAuth

        return GCPDBAuth()
    raise CloudProviderNotImplementedError(provider, BackendCapability.DATABASE_AUTH)


def get_secrets_store() -> SecretsStore:
    """Return a SecretsStore implementation for the configured provider."""
    from installation.contract import BackendCapability

    provider = _require_capability(BackendCapability.SECRETS)
    if provider == "aws":
        from cloud.aws.secrets import AWSSecretsStore

        return AWSSecretsStore()
    if provider == "gcp":
        from cloud.gcp.secrets import GCPSecretsStore

        return GCPSecretsStore()
    raise CloudProviderNotImplementedError(provider, BackendCapability.SECRETS)


def get_object_storage() -> ObjectStorage:
    """Return an ObjectStorage implementation for the configured provider."""
    from installation.contract import BackendCapability

    provider = _require_capability(BackendCapability.STORAGE)
    if provider == "aws":
        from cloud.aws.storage import AWSObjectStorage

        return AWSObjectStorage()
    if provider == "gcp":
        from cloud.gcp.storage import GCPObjectStorage

        return GCPObjectStorage()
    raise CloudProviderNotImplementedError(provider, BackendCapability.STORAGE)


def get_network_inventory() -> NetworkInventory:
    """Return a NetworkInventory implementation for the configured provider."""
    from installation.contract import BackendCapability

    provider = _require_capability(BackendCapability.NETWORK_INVENTORY)
    if provider == "aws":
        from cloud.aws.network import AWSNetworkInventory

        return AWSNetworkInventory()
    if provider == "gcp":
        from cloud.gcp.network import GCPNetworkInventory

        return GCPNetworkInventory()
    raise CloudProviderNotImplementedError(provider, BackendCapability.NETWORK_INVENTORY)
