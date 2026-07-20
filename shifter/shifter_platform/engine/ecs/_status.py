"""Provisioner task-status projection.

Reads a task's status through the ``shared.cloud`` task-runner port and projects
it into the bounded dict callers consume. Split out of ``engine/ecs.py`` (#685).
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

from shared.cloud import get_task_runner
from shared.cloud.exceptions import CloudTaskError

# Log under the stable "engine.ecs" namespace (asserted by tests and used in
# dashboards) even though this code now lives in a package submodule.
logger = logging.getLogger("engine.ecs")


def _project_task_status(result: dict[str, Any] | None) -> dict[str, Any]:
    """Project a raw task-runner status result into the bounded caller dict."""
    if result is None:
        return {"status": "UNKNOWN", "reason": "Task not found"}
    return {
        "status": result.get("status", "UNKNOWN"),
        "desired_status": result.get("desired_status"),
        "started_at": result.get("started_at"),
        "stopped_at": result.get("stopped_at"),
        "stopped_reason": result.get("stopped_reason"),
    }


def get_task_status(task_arn: str) -> dict[str, Any] | None:
    """Get the status of an ECS task.

    Args:
        task_arn: ARN of the ECS task to check

    Returns:
        Dict with status info, or None if not configured
    """
    cluster = getattr(settings, "ENGINE_TASK_CLUSTER", None) or getattr(settings, "ENGINE_ECS_CLUSTER_ARN", None)
    if not task_arn or not cluster:
        return None

    try:
        runner = get_task_runner()
        result = runner.get_task_status(cluster=cluster, task_id=task_arn)
    except CloudTaskError as e:
        logger.exception("Failed to get task status: %s", e)
        return None

    return _project_task_status(result)
