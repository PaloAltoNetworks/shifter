"""Shared helpers for GCP cloud adapters."""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Protocol

from django.conf import settings

_PROJECTS_PREFIX = "projects/"


class _TopicPathClient(Protocol):
    """Minimal Pub/Sub publisher surface used to resolve topic paths."""

    def topic_path(self, project: str, topic: str) -> str:
        """Return the fully-qualified path for ``topic`` in ``project``."""
        ...


class _SubscriptionPathClient(Protocol):
    """Minimal Pub/Sub subscriber surface used to resolve subscription paths."""

    def subscription_path(self, project: str, subscription: str) -> str:
        """Return the fully-qualified path for ``subscription`` in ``project``."""
        ...


def get_project_id() -> str:
    """Return the active GCP project ID."""
    project_id = (
        getattr(settings, "GCP_PROJECT_ID", None)
        or getattr(settings, "GOOGLE_CLOUD_PROJECT", None)
        or getattr(settings, "CLOUD_PROJECT_ID", None)
        or ""
    )
    return str(project_id)


def get_region() -> str:
    """Return the active GCP region."""
    region = getattr(settings, "GCP_REGION", None) or getattr(settings, "CLOUD_REGION", None) or ""
    return str(region)


def import_google_module(module_name: str) -> ModuleType:
    """Import a Google Cloud module lazily.

    The repo does not require Google libraries in AWS-only flows, so GCP adapters
    avoid importing them at module import time.
    """
    return importlib.import_module(module_name)


def build_topic_path(topic_id: str, publisher_client: _TopicPathClient) -> str:
    """Resolve a fully-qualified Pub/Sub topic path for ``topic_id``."""
    if topic_id.startswith(_PROJECTS_PREFIX):
        return topic_id
    project_id = get_project_id()
    if not project_id:
        raise ValueError("GCP project ID is required to resolve a Pub/Sub topic")
    return publisher_client.topic_path(project_id, topic_id)


def build_subscription_path(subscription_id: str, subscriber_client: _SubscriptionPathClient) -> str:
    """Resolve a fully-qualified Pub/Sub subscription path for ``subscription_id``."""
    if subscription_id.startswith(_PROJECTS_PREFIX):
        return subscription_id
    project_id = get_project_id()
    if not project_id:
        raise ValueError("GCP project ID is required to resolve a Pub/Sub subscription")
    return subscriber_client.subscription_path(project_id, subscription_id)


def build_secret_version_name(secret_id: str) -> str:
    """Resolve a fully-qualified Secret Manager secret version name for ``secret_id``."""
    if "/versions/" in secret_id:
        return secret_id
    if secret_id.startswith(_PROJECTS_PREFIX):
        return f"{secret_id}/versions/latest"
    project_id = get_project_id()
    if not project_id:
        raise ValueError("GCP project ID is required to resolve a Secret Manager secret")
    return f"{_PROJECTS_PREFIX}{project_id}/secrets/{secret_id}/versions/latest"
