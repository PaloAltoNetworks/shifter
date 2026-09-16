"""Range lifecycle-target classification.

Maps a range's ``engine_instance`` rows onto per-instance lifecycle-execution
entries (AWS EC2, GDC VM Runtime, GDC scenario Pod, or GCE VM) for the
pause/resume orchestrator. Split out of ``_pause_resume`` so orchestration and
classification stay small and separately testable; the entries and
``get_range_instance_ids`` are re-exported through the ``range_ops`` package so
existing callers and test patches resolve unchanged.
"""

from __future__ import annotations

import logging
from typing import Any

from events import STATUS_PAUSED, STATUS_READY

logger = logging.getLogger(__name__)

_GCP_RANGE_LIFECYCLE_NOT_IMPLEMENTED = (
    "GCP scenario Pod pause/resume is not lossless: pod-backed assets do not "
    "preserve runtime state across pause/resume, so a range containing one is "
    "unsupported until parity work promotes or excludes it."
)


# (cloud_provider, asset_type) -> operation_mode for non-AWS lifecycle targets.
_GCP_OPERATION_MODES = {
    ("gcp", "gce_vm"): "gce_vm",
    ("gcp", "vm_runtime_vm"): "gdc_vm_runtime",
    ("gcp", "scenario_pod"): "gdc_scenario_pod",
}


def _build_aws_lifecycle_entry(
    entry: dict[str, object], state_dict: dict[str, object], uuid: object, role: str
) -> dict[str, object]:
    """Finalize an AWS lifecycle entry, failing closed when provider state is missing.

    An AWS instance without an ``aws_instance_id`` cannot be paused/resumed. Per
    ADR-039 fail-before-mutation, an incomplete member fails the whole operation
    before any mutation rather than being silently skipped (issue #614).
    """
    aws_instance_id = state_dict.get("aws_instance_id")
    if not aws_instance_id:
        raise ValueError(f"AWS range instance {uuid} (role={role}) is missing aws_instance_id in state")
    entry["operation_mode"] = "aws"
    entry["aws_instance_id"] = aws_instance_id
    return entry


def _build_range_lifecycle_entry(
    request_id: str,
    uuid: object,
    state: object,
    role: str,
    name: str | None,
) -> dict[str, object]:
    """Build the lifecycle-operation entry for one instance.

    Fails closed (raises ``ValueError``) for an AWS instance missing its
    ``aws_instance_id`` or an unsupported ``(cloud_provider, asset_type)`` target,
    so an incomplete or unmappable member fails before any mutation (ADR-039).
    """
    state_dict = state if isinstance(state, dict) else {}
    cloud_provider = str(state_dict.get("cloud_provider", "aws")).strip().lower() or "aws"
    asset_type = str(state_dict.get("asset_type", "vm_runtime_vm")).strip() or "vm_runtime_vm"
    entry: dict[str, object] = {
        "uuid": str(uuid),
        "name": name or "",
        "role": role,
        "cloud_provider": cloud_provider,
        "asset_type": asset_type,
        "state": state_dict,
    }

    if cloud_provider == "aws":
        return _build_aws_lifecycle_entry(entry, state_dict, uuid, role)

    operation_mode = _GCP_OPERATION_MODES.get((cloud_provider, asset_type))
    if operation_mode is None:
        raise ValueError(
            "Unsupported range lifecycle target "
            f"for request {request_id}: cloud_provider={cloud_provider!r} asset_type={asset_type!r}"
        )
    entry["operation_mode"] = operation_mode
    return entry


def get_range_instance_ids(request_id: str) -> list[dict[str, Any]]:
    """Get all range assets for pause/resume operations.

    Queries engine_instance records for the given request and extracts
    provider/runtime-specific lifecycle targets from the state JSON field.

    Args:
        request_id: UUID string of the Request.

    Returns:
        List of dicts describing how each asset should participate in
        lifecycle operations.

    Raises:
        ValueError: If no instances are found or an instance cannot be mapped
            onto a supported lifecycle mode.
    """
    logger.info("get_range_instance_ids: request_id=%s", request_id)

    # Late-bound call to ``range_ops.get_db_connection`` so test patches
    # applied at the package level still apply here.
    import range_ops as _pkg

    with _pkg.get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT i.uuid, i.state, i.role, i.name
            FROM engine_instance i
            JOIN engine_request r ON i.request_id = r.id
            WHERE r.request_id = %s
              AND i.status IN (%s, %s)
            """,
            (request_id, STATUS_READY, STATUS_PAUSED),
        )
        rows = cur.fetchall()

    if not rows:
        raise ValueError(f"No instances found for request: {request_id}")

    instances = [_build_range_lifecycle_entry(request_id, uuid, state, role, name) for uuid, state, role, name in rows]

    if not instances:
        raise ValueError(f"No lifecycle-managed assets found for request: {request_id}")

    logger.info(
        "get_range_instance_ids: found %d instances for request_id=%s",
        len(instances),
        request_id,
    )
    return instances
