"""GCE range-cell guest power operations (pause/resume) for issue #614.

Stops and starts a Compute Engine range-cell VM through the existing
``ComputeInstancesClient`` and observes the resulting instance state, so a range
pause/resume reaches its declared postcondition (ADR-039) rather than trusting
that the provider accepted the request. The persistent boot disk survives a stop,
so GCE stop/start is lossless.

Addressing comes from the per-instance state persisted by the range-cell output
builder. Those provider-prefixed output keys are persisted into
``engine_instance.state`` under ``provider_metadata.gcp`` with the ``gcp_``
prefix removed (``project_id``, ``zone``, ``instance_name``) by
``state_helpers._build_instance_state``; the raw provisioner output carries the
same values under the ``gcp_``-prefixed top-level keys. Both shapes are accepted.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from gcp_range_cell_clients import GCEClients, _build_clients
from gcp_range_cell_ops import _wait_for_operation
from gcp_range_cell_types import RangeCellPlan
from log_redact import safe_log_fingerprint

logger = logging.getLogger(__name__)

# Compute Engine terminal instance states for the two power operations.
_STOPPED_STATUS = "TERMINATED"
_RUNNING_STATUS = "RUNNING"

_EXPECTED_STATUS = {"stop": _STOPPED_STATUS, "start": _RUNNING_STATUS}


def _gcp_metadata(state: dict[str, Any]) -> dict[str, Any]:
    """Return the ``provider_metadata.gcp`` block of a persisted instance state."""
    provider_metadata = state.get("provider_metadata")
    if isinstance(provider_metadata, dict):
        metadata = provider_metadata.get("gcp")
        if isinstance(metadata, dict):
            return metadata
    return {}


def _resolve_power_target(state: dict[str, Any]) -> tuple[str, str, str]:
    """Resolve the (project, zone, instance) a GCE power op addresses from state.

    Reads the persisted ``provider_metadata.gcp`` block first (``project_id`` /
    ``zone`` / ``instance_name``), falling back to the raw provisioner output's
    ``gcp_``-prefixed top-level keys and ``instance_id``.
    """
    metadata = _gcp_metadata(state)
    project = str(metadata.get("project_id") or state.get("gcp_project_id") or "").strip()
    zone = str(metadata.get("zone") or state.get("gcp_zone") or "").strip()
    instance = str(
        metadata.get("instance_name") or state.get("gcp_instance_name") or state.get("instance_id") or ""
    ).strip()
    if not all([project, zone, instance]):
        raise RuntimeError(
            "GCE range-cell power operation requires project, zone, and instance name in state "
            "(provider_metadata.gcp or gcp_-prefixed output keys)"
        )
    return project, zone, instance


def _instance_status(instance: object) -> str:
    """Read a Compute instance status from an SDK object or dict response."""
    if isinstance(instance, dict):
        return str(instance.get("status", "")).upper()
    return str(getattr(instance, "status", "") or "").upper()


def run_power_operation(operation: str, state: dict[str, Any], *, clients: GCEClients | None = None) -> None:
    """Run a start/stop power operation against a GCE range-cell VM and observe it.

    Args:
        operation: "start" (resume) or "stop" (pause).
        state: The instance's persisted ``engine_instance.state`` dict.
        clients: Optional injected Compute clients (tests); production builds them.

    Raises:
        ValueError: On an unknown operation.
        RuntimeError: On incomplete state or when the instance does not reach the
            expected terminal status.
    """
    if operation not in _EXPECTED_STATUS:
        raise ValueError(f"Unknown GCE range-cell operation: {operation}")

    project, zone, instance = _resolve_power_target(state)
    resolved = clients or _build_clients()
    # ``_wait_for_operation`` only reads project_id/zone for the zone scope; the
    # remaining RangeCellPlan keys are unused here.
    plan = cast(RangeCellPlan, {"project_id": project, "zone": zone, "region": ""})

    if operation == "stop":
        compute_operation = resolved.instances.stop(project=project, zone=zone, instance=instance)
    else:
        compute_operation = resolved.instances.start(project=project, zone=zone, instance=instance)
    _wait_for_operation(plan, resolved, compute_operation, "zone")

    expected = _EXPECTED_STATUS[operation]
    current = resolved.instances.get(project=project, zone=zone, instance=instance)
    status = _instance_status(current)
    if status != expected:
        raise RuntimeError(
            f"GCE instance name_fp={safe_log_fingerprint(instance)} did not reach {expected} "
            f"after {operation} (observed status={status or '<unknown>'})"
        )
    logger.info(
        "GCE range-cell %s complete name_fp=%s status=%s",
        operation,
        safe_log_fingerprint(instance),
        expected,
    )
