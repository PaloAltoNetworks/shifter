"""NGFW pause/resume/status helpers used during range lifecycle transitions.

Handles the NGFW side of range pause/resume: deciding whether the shared
NGFW can be paused, stopping/starting its EC2 instance, and propagating
status to the database and event bus.
"""

from __future__ import annotations

import logging
from typing import Any

from plans.ngfw_stop import NGFWStopPlan

logger = logging.getLogger(__name__)

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
              AND status NOT IN ('destroyed', 'failed')
            GROUP BY status
            """,
            (ngfw_instance_id, exclude_range_id),
        )
        rows = cur.fetchall()

    counts = {row[0]: row[1] for row in rows}
    logger.debug("should_pause_ngfw: other range counts=%s", counts)

    # RESUMING wins - don't pause if any range is resuming
    if counts.get("resuming", 0) > 0:
        logger.info(
            "should_pause_ngfw: False - %d ranges resuming",
            counts["resuming"],
        )
        return False

    # Don't pause if any range is ready
    if counts.get("ready", 0) > 0:
        logger.info(
            "should_pause_ngfw: False - %d ranges ready",
            counts["ready"],
        )
        return False

    logger.info("should_pause_ngfw: True - no other active ranges")
    return True


def _update_ngfw_status(ngfw_instance_id: int, status: str) -> None:
    """Update NGFW Instance and App status in database.

    Args:
        ngfw_instance_id: DB ID of the NGFW Instance.
        status: New status value (e.g., "pausing", "paused", "resuming").
    """
    # Late-bound call to ``range_ops.get_db_connection`` so test patches
    # applied at the package level still apply here.
    import range_ops as _pkg

    with _pkg.get_db_connection() as conn, conn.cursor() as cur:
        # Update instance status
        cur.execute(
            """
            UPDATE engine_instance
            SET status = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (status, ngfw_instance_id),
        )

        # Update app status if exists
        cur.execute(
            """
            UPDATE engine_app
            SET status = %s, updated_at = NOW()
            WHERE instance_id = %s
            """,
            (status, ngfw_instance_id),
        )
        conn.commit()

    logger.debug(
        "_update_ngfw_status: updated ngfw_instance_id=%s status=%s",
        ngfw_instance_id,
        status,
    )


def pause_ngfw_for_range(request_id: str) -> None:
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
    if ngfw_info["status"] in ("paused", "pausing"):
        logger.info(
            "pause_ngfw_for_range: NGFW already %s, skipping",
            ngfw_info["status"],
        )
        return

    # Check if other ranges need the NGFW
    if not should_pause_ngfw(ngfw_info["ngfw_instance_id"], ngfw_info["range_id"]):
        logger.info("pause_ngfw_for_range: other ranges need NGFW, skipping")
        return

    # Update status to pausing
    _pkg._update_ngfw_status(ngfw_info["ngfw_instance_id"], "pausing")

    # Publish event
    _pkg.publish_ngfw_event(
        request_id=ngfw_info["ngfw_request_id"],
        instance_id=ngfw_info["instance_uuid"],
        app_id=ngfw_info["app_id"],
        status="pausing",
    )

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
        _pkg._update_ngfw_status(ngfw_info["ngfw_instance_id"], "failed")
        _pkg.publish_ngfw_event(
            request_id=ngfw_info["ngfw_request_id"],
            instance_id=ngfw_info["instance_uuid"],
            app_id=ngfw_info["app_id"],
            status="failed",
        )
        raise RuntimeError(error_msg)

    # Update status to paused
    _pkg._update_ngfw_status(ngfw_info["ngfw_instance_id"], "paused")

    # Publish success event
    _pkg.publish_ngfw_event(
        request_id=ngfw_info["ngfw_request_id"],
        instance_id=ngfw_info["instance_uuid"],
        app_id=ngfw_info["app_id"],
        status="paused",
    )

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


def _publish_ngfw_status(ngfw_info: dict[str, Any], status: str) -> None:
    """Persist `status` and emit the matching event for an NGFW lifecycle transition."""
    # Late-bound calls to package-level names so test patches applied at
    # the package level still apply here.
    import range_ops as _pkg

    _pkg._update_ngfw_status(ngfw_info["ngfw_instance_id"], status)
    _pkg.publish_ngfw_event(
        request_id=ngfw_info["ngfw_request_id"],
        instance_id=ngfw_info["instance_uuid"],
        app_id=ngfw_info["app_id"],
        status=status,
    )


def _run_ngfw_start_with_retry(ngfw_info: dict[str, Any], request_id: str) -> None:
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
            _publish_ngfw_status(ngfw_info, "failed")
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
        if refreshed and refreshed["status"] == "ready":
            logger.info(
                "ensure_ngfw_running: NGFW became ready during retry wait, request_id=%s",
                request_id,
            )
            return


def ensure_ngfw_running(request_id: str) -> None:
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
    if status == "ready":
        logger.info("ensure_ngfw_running: NGFW already ready, skipping")
        return
    if status == "failed":
        raise RuntimeError("NGFW is in failed state, cannot resume range")
    if status == "resuming":
        logger.info("ensure_ngfw_running: NGFW is resuming, waiting...")
        # Fall through; AWSExecutor.wait_for_running will block.
    if status == "pausing":
        _wait_for_ngfw_pause_to_complete(ngfw_info)
    if status not in ("paused", "pausing", "resuming"):
        return

    _publish_ngfw_status(ngfw_info, "resuming")
    _run_ngfw_start_with_retry(ngfw_info, request_id)
    _publish_ngfw_status(ngfw_info, "ready")
    logger.info(
        "ensure_ngfw_running: NGFW resumed ec2=%s request_id=%s",
        ngfw_info["ec2_instance_id"],
        request_id,
    )
