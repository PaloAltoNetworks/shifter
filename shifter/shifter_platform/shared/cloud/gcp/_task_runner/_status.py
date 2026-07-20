"""``get_task_status`` support: reading Job status and building the
ECS-shaped status payload TaskRunner callers expect.

Split out of the historical monolithic ``task_runner.py`` (#561).
"""

from __future__ import annotations

import logging
from typing import Any

from ._helpers import _KUBERNETES_REQUEST_TIMEOUT_SECONDS, _api_call, _derive_job_state, _job_condition_reason

logger = logging.getLogger(__name__)


def _extract_stopped_reason(core_api: object, namespace: str, job_name: str) -> str | None:
    """Return the terminated-container message/reason for a finished Job's pod, if any."""
    try:
        pods = _api_call(
            core_api,
            "list_namespaced_pod",
            namespace=namespace,
            label_selector=f"job-name={job_name}",
            _request_timeout=_KUBERNETES_REQUEST_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.debug("get_task_status: failed to list pods for job=%s", job_name, exc_info=True)
        return None

    for pod in getattr(pods, "items", []):
        container_statuses = getattr(getattr(pod, "status", None), "container_statuses", None) or []
        for container_status in container_statuses:
            state = getattr(container_status, "state", None)
            terminated = getattr(state, "terminated", None)
            if terminated:
                return getattr(terminated, "message", None) or getattr(terminated, "reason", None)
    return None


def _read_job_status(batch_api: object, namespace: str, job_name: str, api_exception: type[Exception]) -> object | None:
    """Return the named Job's status object, or ``None`` on a 404."""
    try:
        return _api_call(
            batch_api,
            "read_namespaced_job_status",
            name=job_name,
            namespace=namespace,
            _request_timeout=_KUBERNETES_REQUEST_TIMEOUT_SECONDS,
        )
    except api_exception as e:
        if getattr(e, "status", None) == 404:
            return None
        raise


def _build_status_payload(status: object, core_api: object, namespace: str, job_name: str) -> dict[str, Any]:
    """Build the ECS-shaped status payload from a Kubernetes Job status."""
    active = int(getattr(status, "active", 0) or 0)
    failed = int(getattr(status, "failed", 0) or 0)
    succeeded = int(getattr(status, "succeeded", 0) or 0)
    started_at = getattr(status, "start_time", None)
    stopped_at = getattr(status, "completion_time", None)

    stopped_reason = _job_condition_reason(status)
    state = _derive_job_state(active=active, failed=failed, succeeded=succeeded)

    if state in {"SUCCEEDED", "FAILED"} and not stopped_reason:
        stopped_reason = _extract_stopped_reason(core_api, namespace, job_name)

    return {
        "task_id": f"{namespace}/{job_name}",
        "status": state,
        "desired_status": "RUNNING" if state in {"SUBMITTED", "RUNNING"} else "COMPLETED",
        "started_at": started_at,
        "stopped_at": stopped_at,
        "stopped_reason": stopped_reason,
    }
