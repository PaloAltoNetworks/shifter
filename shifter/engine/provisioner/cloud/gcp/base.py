"""Shared helpers for provisioner-side GCP adapters."""

from __future__ import annotations

import importlib
import os
from types import ModuleType
from typing import Protocol


class SupportsTopicPath(Protocol):
    """Structural type for the Pub/Sub client method ``build_topic_path`` needs."""

    def topic_path(self, project: str, topic: str) -> str: ...


def import_google_module(module_name: str) -> ModuleType:
    """Import a Google Cloud module lazily."""
    return importlib.import_module(module_name)


def get_project_id() -> str:
    """Return the GCP project ID from the environment (empty string if unset)."""
    return (
        os.environ.get("GCP_PROJECT_ID")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
        or os.environ.get("CLOUD_PROJECT_ID")
        or ""
    )


def get_region() -> str:
    """Return the GCP region from the environment (empty string if unset)."""
    return os.environ.get("GCP_REGION") or os.environ.get("CLOUD_REGION") or os.environ.get("AWS_REGION", "")


def build_topic_path(topic_id: str, publisher_client: SupportsTopicPath) -> str:
    """Resolve a Pub/Sub topic ID to its fully-qualified topic path."""
    if topic_id.startswith("projects/"):
        return topic_id
    project_id = get_project_id()
    if not project_id:
        raise ValueError("GCP project ID is required to resolve a Pub/Sub topic")
    return publisher_client.topic_path(project_id, topic_id)


def build_secret_version_name(secret_id: str) -> str:
    """Resolve a Secret Manager secret ID to a fully-qualified version name."""
    if "/versions/" in secret_id:
        return secret_id
    if secret_id.startswith("projects/"):
        return f"{secret_id}/versions/latest"
    project_id = get_project_id()
    if not project_id:
        raise ValueError("GCP project ID is required to resolve a Secret Manager secret")
    return f"projects/{project_id}/secrets/{secret_id}/versions/latest"


def normalize_parameter_name(name: str) -> str:
    """Map an SSM-style path to a Secret Manager-friendly identifier."""
    normalized = name.strip("/").replace("/", "--")
    if not normalized:
        raise ValueError("Config parameter name must not be empty")
    return normalized
