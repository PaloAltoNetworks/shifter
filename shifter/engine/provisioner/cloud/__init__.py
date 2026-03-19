"""Cloud provider abstraction layer for the provisioner.

Factory functions that return provider-specific implementations based on
the CLOUD_PROVIDER environment variable. Defaults to "aws".

This module has no Django dependency — it reads os.environ directly.

Usage:
    from cloud import get_event_bus, get_config_store, get_db_auth
    bus = get_event_bus()
    store = get_config_store()
    auth = get_db_auth()
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from cloud.exceptions import CloudProviderNotImplementedError

if TYPE_CHECKING:
    from cloud.types import ConfigStore, DBAuth, EventBus, ObjectStorage


def _get_provider() -> str:
    return os.environ.get("CLOUD_PROVIDER", "aws")


def get_event_bus() -> EventBus:
    """Return an EventBus implementation for the configured provider."""
    provider = _get_provider()
    if provider == "aws":
        from cloud.aws.event_bus import AWSEventBus

        return AWSEventBus()
    raise CloudProviderNotImplementedError(provider)


def get_config_store() -> ConfigStore:
    """Return a ConfigStore implementation for the configured provider."""
    provider = _get_provider()
    if provider == "aws":
        from cloud.aws.config_store import AWSConfigStore

        return AWSConfigStore()
    raise CloudProviderNotImplementedError(provider)


def get_db_auth() -> DBAuth:
    """Return a DBAuth implementation for the configured provider."""
    provider = _get_provider()
    if provider == "aws":
        from cloud.aws.db_auth import AWSDBAuth

        return AWSDBAuth()
    raise CloudProviderNotImplementedError(provider)


def get_object_storage() -> ObjectStorage:
    """Return an ObjectStorage implementation for the configured provider."""
    provider = _get_provider()
    if provider == "aws":
        from cloud.aws.storage import AWSObjectStorage

        return AWSObjectStorage()
    raise CloudProviderNotImplementedError(provider)
