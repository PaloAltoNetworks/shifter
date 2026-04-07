"""Cloud provider abstraction layer for the provisioner.

Factory functions that return provider-specific implementations based on
the CLOUD_PROVIDER environment variable. Defaults to "aws".

This module has no Django dependency — it reads os.environ directly.

Usage:
    from cloud import get_event_bus, get_config_store, get_db_auth, get_secrets_store
    bus = get_event_bus()
    store = get_config_store()
    auth = get_db_auth()
    secrets = get_secrets_store()
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from cloud.exceptions import CloudProviderNotImplementedError

if TYPE_CHECKING:
    from cloud.types import ConfigStore, DBAuth, EventBus, ObjectStorage, SecretsStore


def _get_provider() -> str:
    return os.environ.get("CLOUD_PROVIDER", "aws")


def get_event_bus() -> EventBus:
    """Return an EventBus implementation for the configured provider."""
    provider = _get_provider()
    if provider == "aws":
        from cloud.aws.event_bus import AWSEventBus

        return AWSEventBus()
    if provider == "gcp":
        from cloud.gcp.event_bus import GCPEventBus

        return GCPEventBus()
    raise CloudProviderNotImplementedError(provider)


def get_config_store() -> ConfigStore:
    """Return a ConfigStore implementation for the configured provider."""
    provider = _get_provider()
    if provider == "aws":
        from cloud.aws.config_store import AWSConfigStore

        return AWSConfigStore()
    if provider == "gcp":
        from cloud.gcp.config_store import GCPConfigStore

        return GCPConfigStore()
    raise CloudProviderNotImplementedError(provider)


def get_db_auth() -> DBAuth:
    """Return a DBAuth implementation for the configured provider."""
    provider = _get_provider()
    if provider == "aws":
        from cloud.aws.db_auth import AWSDBAuth

        return AWSDBAuth()
    if provider == "gcp":
        from cloud.gcp.db_auth import GCPDBAuth

        return GCPDBAuth()
    raise CloudProviderNotImplementedError(provider)


def get_secrets_store() -> SecretsStore:
    """Return a SecretsStore implementation for the configured provider."""
    provider = _get_provider()
    if provider == "aws":
        from cloud.aws.secrets import AWSSecretsStore

        return AWSSecretsStore()
    if provider == "gcp":
        from cloud.gcp.secrets import GCPSecretsStore

        return GCPSecretsStore()
    raise CloudProviderNotImplementedError(provider)


def get_object_storage() -> ObjectStorage:
    """Return an ObjectStorage implementation for the configured provider."""
    provider = _get_provider()
    if provider == "aws":
        from cloud.aws.storage import AWSObjectStorage

        return AWSObjectStorage()
    if provider == "gcp":
        from cloud.gcp.storage import GCPObjectStorage

        return GCPObjectStorage()
    raise CloudProviderNotImplementedError(provider)
