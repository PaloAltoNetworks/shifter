"""NGFW pause/resume/status helpers used during range lifecycle transitions.

Handles the NGFW side of range pause/resume: deciding whether the shared
NGFW can be paused, stopping/starting its EC2 instance, and propagating
status to the database and event bus.
"""

from __future__ import annotations

import logging
from types import ModuleType
from typing import Any

from shared.operation_results import ResultStep

from events import (
    STATUS_DESTROYED,
    STATUS_FAILED,
    STATUS_PAUSED,
    STATUS_PAUSING,
    STATUS_READY,
    STATUS_RESUMING,
)
from plans.ngfw_stop import NGFWStopPlan
from provisioner_db_appends import OperationRef, append_operation_step_result

logger = logging.getLogger(__name__)

# ADR-043 phase 4 (#1836): an NGFW power change performed for a Range pause or
# resume is a subordinate step of that Range generation, keyed by
# (owning range operation, reported status).
_CASCADE_STEP_BY_STATUS = {
    ("pause", STATUS_PAUSING): ResultStep.RANGE_NGFW_CASCADE_PAUSING,
    ("pause", STATUS_PAUSED): ResultStep.RANGE_NGFW_CASCADE_PAUSED,
    ("pause", STATUS_FAILED): ResultStep.RANGE_NGFW_CASCADE_FAILED,
    ("resume", STATUS_RESUMING): ResultStep.RANGE_NGFW_CASCADE_RESUMING,
    ("resume", STATUS_READY): ResultStep.RANGE_NGFW_CASCADE_READY,
    ("resume", STATUS_FAILED): ResultStep.RANGE_NGFW_CASCADE_FAILED,
}

NGFW_START_MAX_RETRIES = 3
NGFW_START_RETRY_DELAYS = (10, 30, 60)


def get_range_ngfw_info(request_id: str) -> dict | None:
    """Get NGFW instance information for a range.

    Queries the range's attached NGFW (via ngfw_instance FK) and returns
    the NGFW's EC2 instance ID, status, and related identifiers.

    Args:
        request_id: UUID string of the Range's Request.

    Returns:
        Dict with NGFW info if attached, None otherwise:
        - ngfw_instance_id: DB ID of the NGFW Instance record
        - ngfw_request_id: UUID string of the NGFW's Request
        - ec2_instance_id: AWS EC2 instance ID (e.g., "i-abc123")
        - instance_uuid: UUID of the NGFW Instance
        - status: Current NGFW status (e.g., "ready", "paused")
        - app_id: UUID of the NGFW App (may be None)
        - range_id: DB ID of the Range
    """
    logger.debug("get_range_ngfw_info: request_id=%s", request_id)

    # Late-bound call to ``range_ops.get_db_connection`` so test patches
    # applied at the package level still apply here.
    import range_ops as _pkg

    with _pkg.get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                ei.id AS ngfw_instance_id,
                er.request_id AS ngfw_request_id,
                ei.state->>'ec2_instance_id' AS ec2_instance_id,
                ei.uuid AS instance_uuid,
                ei.status,
                ea.uuid AS app_id,
                rng.id AS range_id
            FROM mission_control_range rng
            JOIN engine_request req ON rng.request_id = req.id
            JOIN engine_instance ei ON rng.ngfw_instance_id = ei.id
            JOIN engine_request er ON ei.request_id = er.id
            LEFT JOIN engine_app ea ON ea.instance_id = ei.id
            WHERE req.request_id = %s
              AND rng.ngfw_instance_id IS NOT NULL
            """,
            (request_id,),
        )
        row = cur.fetchone()

    if not row:
        logger.debug("get_range_ngfw_info: no NGFW attached request_id=%s", request_id)
        return None

    result = {
        "ngfw_instance_id": row[0],
        "ngfw_request_id": str(row[1]),
        "ec2_instance_id": row[2],
        "instance_uuid": str(row[3]) if row[3] else None,
        "status": row[4],
        "app_id": str(row[5]) if row[5] else None,
        "range_id": row[6],
    }
    logger.debug(
        "get_range_ngfw_info: found NGFW status=%s ec2=%s request_id=%s",
        result["status"],
        result["ec2_instance_id"],
        request_id,
    )
    return result


def _require_aws_ngfw_cascade(ngfw_info: dict[str, Any]) -> None:
    """Fail closed when an attached NGFW is not the AWS EC2 cascade this path drives.

    The range pause/resume NGFW cascade stops/starts an EC2 instance. A range that
    ever attaches a non-AWS (e.g. GCP VM-Series) NGFW has no ``ec2_instance_id``;
    rather than silently driving the AWS executor with a missing id, fail closed
    with a clear diagnostic (ADR-039 honest-failure). GCP ranges do not attach an
    NGFW through this FK today, so this cannot fire on the current GCP paths.
    """
    if not ngfw_info.get("ec2_instance_id"):
        raise RuntimeError("Range NGFW cascade requires an AWS EC2 NGFW; the attached NGFW has no ec2_instance_id")


def should_pause_ngfw(ngfw_instance_id: int, exclude_range_id: int) -> bool:
    """Check if NGFW should be paused (no other ranges READY or RESUMING).

    Args:
        ngfw_instance_id: DB ID of the NGFW Instance.
        exclude_range_id: Range ID to exclude (the range being paused).

    Returns:
        True if NGFW can be safely paused, False if other ranges need it.
    """
    logger.debug(
        "should_pause_ngfw: ngfw_instance_id=%s exclude_range_id=%s",
        ngfw_instance_id,
        exclude_range_id,
    )

    # Late-bound call to ``range_ops.get_db_connection`` so test patches
    # applied at the package level still apply here.
    import range_ops as _pkg

    with _pkg.get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT status, COUNT(*) as count
            FROM mission_control_range
            WHERE ngfw_instance_id = %s
              AND id != %s
              AND status NOT IN (%s, %s)
            GROUP BY status
            """,
            (ngfw_instance_id, exclude_range_id, STATUS_DESTROYED, STATUS_FAILED),
        )
        rows = cur.fetchall()

    counts = {row[0]: row[1] for row in rows}
    logger.debug("should_pause_ngfw: other range counts=%s", counts)

    # RESUMING wins - don't pause if any range is resuming
    if counts.get(STATUS_RESUMING, 0) > 0:
        logger.info(
            "should_pause_ngfw: False - %d ranges resuming",
            counts[STATUS_RESUMING],
        )
        return False

    # Don't pause if any range is ready
    if counts.get(STATUS_READY, 0) > 0:
        logger.info(
            "should_pause_ngfw: False - %d ranges ready",
            counts[STATUS_READY],
        )
        return False

    logger.info("should_pause_ngfw: True - no other active ranges")
    return True


def _update_ngfw_status(
    ngfw_instance_id: int,
    status: str,
    *,
    instance_uuid: str | None = None,
    ref: OperationRef | None = None,
    operation: str | None = None,
) -> None:
    """Report an NGFW cascade transition to the Engine result inbox.

    ADR-043 phase 4 (#1836): this no longer writes ``engine_instance`` /
    ``engine_app``. The cascade is a *subordinate* result of the owning Range
    operation, so it is reported under that generation; the applier re-checks the
    Range-to-NGFW attachment and whether another attached range still needs the
    NGFW before applying it. ``should_pause_ngfw`` remains a pre-cloud
    compatibility check, not authorization.

    Args:
        ngfw_instance_id: DB id of the NGFW Instance (logging correlation only —
            never identity for the write).
        status: New status value ("pausing", "paused", "resuming", "ready", "failed").
        instance_uuid: UUID of the NGFW Instance; the applier's identity key.
        ref: Identity of the owning Range operation generation.
        operation: The owning range operation ("pause" or "resume").
    """
    if operation is None:
        raise ValueError("NGFW cascade result requires the owning range operation")
    step = _CASCADE_STEP_BY_STATUS.get((operation, status))
    if step is None:
        raise ValueError(f"no cascade result step declared for {operation}:{status}")
    if instance_uuid is None:
        raise ValueError("NGFW cascade result requires the instance UUID")

    append_operation_step_result(
        ref,
        resource="range",
        operation=str(operation),
        step=step,
        result_payload={"ngfw_instance_uuid": str(instance_uuid), "status": status},
    )
    logger.debug(
        "_update_ngfw_status: reported ngfw_instance_id=%s status=%s step=%s",
        ngfw_instance_id,
        status,
        step,
    )


def pause_ngfw_for_range(request_id: str, *, ref: OperationRef | None = None) -> None:
    """Pause NGFW if no other ranges need it.

    Called after a range is paused. Checks if any other ranges are using
    the same NGFW - if not, stops the NGFW EC2 instance.

    Idempotent: safe to call even if NGFW is already paused.

    Args:
        request_id: UUID string of the Range's Request.
    """
    logger.info("pause_ngfw_for_range: starting request_id=%s", request_id)

    # Late-bound calls to package-level names so test patches applied at
    # the package level still apply here.
    import range_ops as _pkg

    # Get NGFW info
    ngfw_info = _pkg.get_range_ngfw_info(request_id)
    if not ngfw_info:
        logger.info("pause_ngfw_for_range: no NGFW attached, skipping")
        return

    # Idempotent: already paused or pausing
    if ngfw_info["status"] in (STATUS_PAUSED, STATUS_PAUSING):
        logger.info(
            "pause_ngfw_for_range: NGFW already %s, skipping",
            ngfw_info["status"],
        )
        return

    # Check if other ranges need the NGFW
    if not should_pause_ngfw(ngfw_info["ngfw_instance_id"], ngfw_info["range_id"]):
        logger.info("pause_ngfw_for_range: other ranges need NGFW, skipping")
        return

    # Fail closed before mutation if the attached NGFW is not the AWS EC2 cascade.
    _require_aws_ngfw_cascade(ngfw_info)

    # Report the cascade transition; the applier owns the write and the event.
    _report_cascade(_pkg, ngfw_info, STATUS_PAUSING, ref=ref, operation="pause")

    # Execute stop plan
    executor = _pkg.AWSExecutor()
    orchestrator = _pkg.OpsOrchestrator(executor)
    plan = NGFWStopPlan()

    # Create a simple object with instance_id attribute for get_context
    class InstanceRef:
        """Minimal instance_id holder satisfying the NGFWStopPlan.get_context contract."""

        def __init__(self, instance_id: str) -> None:
            self.instance_id = instance_id

    context = plan.get_context(InstanceRef(ngfw_info["ec2_instance_id"]))
    result = orchestrator.orchestrate(ngfw_info["ec2_instance_id"], plan, context)

    if not result.success:
        error_msg = result.error or "NGFW stop failed"
        logger.error("pause_ngfw_for_range: %s", error_msg)
        _report_cascade(_pkg, ngfw_info, STATUS_FAILED, ref=ref, operation="pause")
        raise RuntimeError(error_msg)

    _report_cascade(_pkg, ngfw_info, STATUS_PAUSED, ref=ref, operation="pause")

    logger.info(
        "pause_ngfw_for_range: NGFW paused ec2=%s request_id=%s",
        ngfw_info["ec2_instance_id"],
        request_id,
    )


def _wait_for_ngfw_pause_to_complete(ngfw_info: dict[str, Any]) -> None:
    """If the NGFW is mid-`pausing`, block until EC2 reports stopped before resuming."""
    logger.info("ensure_ngfw_running: NGFW is pausing, waiting for paused...")

    # Late-bound call to ``range_ops.AWSExecutor`` so test patches applied
    # at the package level still apply here.
    import range_ops as _pkg

    executor = _pkg.AWSExecutor()
    wait_result = executor.wait_for_stopped(ngfw_info["ec2_instance_id"])
    if not wait_result.success:
        raise RuntimeError(f"NGFW failed to reach paused state: {wait_result.stderr}")
    logger.info("ensure_ngfw_running: NGFW is now paused, proceeding to resume")


def _report_cascade(
    _pkg: ModuleType,
    ngfw_info: dict[str, Any],
    status: str,
    *,
    ref: OperationRef | None,
    operation: str,
) -> None:
    """Report one NGFW cascade transition under the owning Range generation."""
    _pkg._update_ngfw_status(
        ngfw_info["ngfw_instance_id"],
        status,
        instance_uuid=ngfw_info["instance_uuid"],
        ref=ref,
        operation=operation,
    )


def _publish_ngfw_status(ngfw_info: dict[str, Any], status: str, *, ref: OperationRef | None = None) -> None:
    """Report an NGFW lifecycle transition for a Range resume cascade."""
    # Late-bound calls to package-level names so test patches applied at
    # the package level still apply here.
    import range_ops as _pkg

    _report_cascade(_pkg, ngfw_info, status, ref=ref, operation="resume")


def _run_ngfw_start_with_retry(ngfw_info: dict[str, Any], request_id: str, *, ref: OperationRef | None = None) -> None:
    """Run NGFWStartPlan with bounded retries; raise RuntimeError on permanent failure.

    Returns early without raising if a parallel resume marks the NGFW ready
    between attempts.
    """
    # Late-bound calls to package-level names so test patches applied at
    # the package level still apply here.
    import range_ops as _pkg

    executor = _pkg.AWSExecutor()
    orchestrator = _pkg.OpsOrchestrator(executor)
    plan = _pkg.NGFWStartPlan()

    class _InstanceRef:
        """Minimal instance_id holder satisfying the NGFWStartPlan.get_context contract."""

        def __init__(self, instance_id: str) -> None:
            self.instance_id = instance_id

    context = plan.get_context(_InstanceRef(ngfw_info["ec2_instance_id"]))

    for attempt in range(NGFW_START_MAX_RETRIES):
        result = orchestrator.orchestrate(ngfw_info["ec2_instance_id"], plan, context)
        if result.success:
            return

        if attempt == NGFW_START_MAX_RETRIES - 1:
            error_msg = result.error or "NGFW start failed"
            logger.error("ensure_ngfw_running: %s", error_msg)
            _publish_ngfw_status(ngfw_info, STATUS_FAILED, ref=ref)
            raise RuntimeError(error_msg)

        delay = NGFW_START_RETRY_DELAYS[attempt]
        logger.warning(
            "ensure_ngfw_running: attempt %d/%d failed, retrying in %ds request_id=%s error=%s",
            attempt + 1,
            NGFW_START_MAX_RETRIES,
            delay,
            request_id,
            result.error,
        )
        _pkg.time.sleep(delay)

        refreshed = _pkg.get_range_ngfw_info(request_id)
        if refreshed and refreshed["status"] == STATUS_READY:
            logger.info(
                "ensure_ngfw_running: NGFW became ready during retry wait, request_id=%s",
                request_id,
            )
            return


def ensure_ngfw_running(request_id: str, *, ref: OperationRef | None = None) -> None:
    """Ensure NGFW is running before resuming range instances.

    Checks if the range's attached NGFW is paused and resumes it if needed.
    Retries up to NGFW_START_MAX_RETRIES times on transient failures before
    giving up. Blocks until the NGFW is in ready state.

    Args:
        request_id: UUID string of the Range's Request.

    Raises:
        RuntimeError: If NGFW is in failed state or fails to start after
            all retry attempts.
    """
    logger.info("ensure_ngfw_running: starting request_id=%s", request_id)

    # Late-bound call to ``range_ops.get_range_ngfw_info`` so test patches
    # applied at the package level still apply here.
    import range_ops as _pkg

    ngfw_info = _pkg.get_range_ngfw_info(request_id)
    if not ngfw_info:
        logger.info("ensure_ngfw_running: no NGFW attached, skipping")
        return

    status = ngfw_info["status"]
    if status == STATUS_READY:
        logger.info("ensure_ngfw_running: NGFW already ready, skipping")
        return
    if status == STATUS_FAILED:
        raise RuntimeError("NGFW is in failed state, cannot resume range")
    # Fail closed before any mutation/wait if the attached NGFW is not the AWS EC2
    # cascade this path drives (it needs the ec2_instance_id below).
    _require_aws_ngfw_cascade(ngfw_info)
    if status == STATUS_RESUMING:
        logger.info("ensure_ngfw_running: NGFW is resuming, waiting...")
        # Fall through; AWSExecutor.wait_for_running will block.
    if status == STATUS_PAUSING:
        _wait_for_ngfw_pause_to_complete(ngfw_info)
    if status not in (STATUS_PAUSED, STATUS_PAUSING, STATUS_RESUMING):
        return

    _publish_ngfw_status(ngfw_info, STATUS_RESUMING, ref=ref)
    _run_ngfw_start_with_retry(ngfw_info, request_id, ref=ref)
    _publish_ngfw_status(ngfw_info, STATUS_READY, ref=ref)
    logger.info(
        "ensure_ngfw_running: NGFW resumed ec2=%s request_id=%s",
        ngfw_info["ec2_instance_id"],
        request_id,
    )
