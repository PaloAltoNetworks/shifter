"""GKE-native Kubernetes Job adapter implementing the TaskRunner protocol.

The implementation is split into the private ``_task_runner`` subpackage (#561)
so no module exceeds 500 lines; responsibilities are spread across
``_types``, ``_helpers``, ``_job_manifest``, ``_job_lifecycle``, ``_secrets``,
``_status``, ``_run_task_flow``, and ``_runner`` (the ``GCPTaskRunner`` class).

This module remains the public face of the adapter so callers keep using
``from shared.cloud.gcp.task_runner import GCPTaskRunner`` exactly as before,
and the AWS/GCP cloud-adapter seam (ADR-005-R1) still pairs
``cloud/aws/task_runner.py`` with ``cloud/gcp/task_runner.py``.
"""

from __future__ import annotations

from shared.cloud.gcp._task_runner import PROVISIONER_CONTAINER_NAME, GCPTaskRunner

__all__ = ("PROVISIONER_CONTAINER_NAME", "GCPTaskRunner")
