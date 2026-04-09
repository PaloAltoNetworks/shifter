"""Shared helpers for GCP cloud adapters."""

from __future__ import annotations

import importlib
import re
from typing import Any

from django.conf import settings


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


def import_google_module(module_name: str) -> Any:
    """Import a Google Cloud module lazily.

    The repo does not require Google libraries in AWS-only flows, so GCP adapters
    avoid importing them at module import time.
    """
    return importlib.import_module(module_name)


def build_topic_path(topic_id: str, publisher_client: Any) -> str:
    if topic_id.startswith("projects/"):
        return topic_id
    project_id = get_project_id()
    if not project_id:
        raise ValueError("GCP project ID is required to resolve a Pub/Sub topic")
    return publisher_client.topic_path(project_id, topic_id)


def build_subscription_path(subscription_id: str, subscriber_client: Any) -> str:
    if subscription_id.startswith("projects/"):
        return subscription_id
    project_id = get_project_id()
    if not project_id:
        raise ValueError("GCP project ID is required to resolve a Pub/Sub subscription")
    return subscriber_client.subscription_path(project_id, subscription_id)


def build_secret_version_name(secret_id: str) -> str:
    if "/versions/" in secret_id:
        return secret_id
    if secret_id.startswith("projects/"):
        return f"{secret_id}/versions/latest"
    project_id = get_project_id()
    if not project_id:
        raise ValueError("GCP project ID is required to resolve a Secret Manager secret")
    return f"projects/{project_id}/secrets/{secret_id}/versions/latest"


_K8S_NAME_PATTERN = re.compile(r"[^a-z0-9-]+")


def sanitize_k8s_name(value: str) -> str:
    """Normalize arbitrary text into a DNS-1123-compatible name fragment."""
    normalized = _K8S_NAME_PATTERN.sub("-", value.lower()).strip("-")
    return normalized or "task"


def build_job_generate_name(container_name: str, command: list[str]) -> str:
    """Build a safe Kubernetes Job `generateName` prefix.

    The API server appends a unique suffix, so keep the prefix short enough to
    remain under the 63-character Job name limit.
    """
    name_parts = [sanitize_k8s_name(container_name), *(sanitize_k8s_name(part) for part in command[:2])]
    prefix = "-".join(part for part in name_parts if part).strip("-") or "task"
    prefix = prefix[:52].rstrip("-") or "task"
    return f"{prefix}-"


def parse_job_task_id(task_id: str, default_namespace: str) -> tuple[str, str]:
    """Parse the task identifier returned by `run_task`.

    Task IDs are returned as `<namespace>/<job-name>` for clarity. For backward
    compatibility, a bare Job name is also accepted and resolved against the
    caller-provided namespace.
    """
    if "/" not in task_id:
        return default_namespace, task_id

    namespace, job_name = task_id.split("/", 1)
    return namespace or default_namespace, job_name
