"""Provider-neutral Kubernetes name generation and task-id parsing.

These helpers are pure DNS-1123 name math with no cloud coupling. They were
extracted from ``shared.cloud.gcp.base`` (#1824) so the neutral Kubernetes task
runner — and any caller that builds an idempotent Job name — depends on the
cloud-neutral ``shared.cloud`` layer rather than a GCP-namespaced module.
"""

from __future__ import annotations

import re
from hashlib import sha256

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


def build_idempotent_job_name(container_name: str, task_identity: str) -> str:
    """Build the stable Job name used for create-or-observe task dispatch."""
    prefix = sanitize_k8s_name(container_name)[:40].rstrip("-") or "task"
    digest = sha256(task_identity.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


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
