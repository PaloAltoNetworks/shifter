"""Shared helpers for provisioner-side GCP adapters."""

from __future__ import annotations

import importlib
import os
from typing import Any


def import_google_module(module_name: str) -> Any:
    """Import a Google Cloud module lazily."""
    return importlib.import_module(module_name)


def get_project_id() -> str:
    return (
        os.environ.get("GCP_PROJECT_ID")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
        or os.environ.get("CLOUD_PROJECT_ID")
        or ""
    )


def get_region() -> str:
    return os.environ.get("GCP_REGION") or os.environ.get("CLOUD_REGION") or os.environ.get("AWS_REGION", "")


def build_topic_path(topic_id: str, publisher_client: Any) -> str:
    if topic_id.startswith("projects/"):
        return topic_id
    project_id = get_project_id()
    if not project_id:
        raise ValueError("GCP project ID is required to resolve a Pub/Sub topic")
    return publisher_client.topic_path(project_id, topic_id)


def build_secret_version_name(secret_id: str) -> str:
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
