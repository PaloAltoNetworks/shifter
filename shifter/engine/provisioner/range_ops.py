"""Range pause/resume operations.

Handles pausing and resuming all EC2 instances in a range.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from events import publish_ngfw_event, publish_status_update
from executors.aws_executor import AWSExecutor
from main import get_db_connection, get_range_data_by_request_id, update_range_status
from orchestrators.ops_orchestrator import OpsOrchestrator
from plans.ngfw_start import NGFWStartPlan
from plans.ngfw_stop import NGFWStopPlan
from plans.range_pause import RangePausePlan
from plans.range_resume import RangeResumePlan

logger = logging.getLogger(__name__)

NGFW_START_MAX_RETRIES = 3
NGFW_START_RETRY_DELAYS = (10, 30, 60)


def get_range_instance_ids(request_id: str) -> list[dict]:
    """Get all instance IDs for a range.

    Queries engine_instance records for the given request and extracts
    provider-specific instance IDs from the state JSON field.

    Args:
        request_id: UUID string of the Request.

    Returns:
        List of dicts with 'uuid' (our instance UUID) and 'aws_instance_id'.

    Raises:
        ValueError: If no instances found or missing AWS instance IDs.
        NotImplementedError: If the range uses a non-AWS provider.
    """
    logger.info("get_range_instance_ids: request_id=%s", request_id)

    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT i.uuid, i.state, i.role
            FROM engine_instance i
            JOIN engine_request r ON i.request_id = r.id
            WHERE r.request_id = %s
              AND i.status IN ('ready', 'paused')
            """,
            (request_id,),
        )
        rows = cur.fetchall()

    if not rows:
        raise ValueError(f"No instances found for request: {request_id}")

    instances = []
    for uuid, state, role in rows:
        state_dict = state if isinstance(state, dict) else {}
        cloud_provider = state_dict.get("cloud_provider", "aws")
        if cloud_provider != "aws":
            raise NotImplementedError(
                "Range pause/resume is still AWS-only. "
                f"Found cloud_provider={cloud_provider!r} for request {request_id}. "
                "The GDC/GCP lifecycle rewrite must land before range pause/resume can support this provider."
            )
        aws_instance_id = state_dict.get("aws_instance_id")

        if not aws_instance_id:
            logger.warning(
                "Instance %s (role=%s) missing aws_instance_id in state, skipping",
                uuid,
                role,
            )
            continue

        instances.append(
            {
                "uuid": str(uuid),
                "aws_instance_id": aws_instance_id,
                "role": role,
            }
        )

    if not instances:
        raise ValueError(f"No instances with AWS instance IDs found for request: {request_id}")

    logger.info(
        "get_range_instance_ids: found %d instances for request_id=%s",
        len(instances),
        request_id,
    )
    return instances


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

    with get_db_connection() as conn, conn.cursor() as cur:
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

    with get_db_connection() as conn, conn.cursor() as cur:
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
    with get_db_connection() as conn, conn.cursor() as cur:
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


def pause_ngfw_for_range(request_id: str, range_data: dict) -> None:
    """Pause NGFW if no other ranges need it.

    Called after a range is paused. Checks if any other ranges are using
    the same NGFW - if not, stops the NGFW EC2 instance.

    Idempotent: safe to call even if NGFW is already paused.

    Args:
        request_id: UUID string of the Range's Request.
        range_data: Dict from get_range_data_by_request_id() with range_id.
    """
    logger.info("pause_ngfw_for_range: starting request_id=%s", request_id)

    # Get NGFW info
    ngfw_info = get_range_ngfw_info(request_id)
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
    _update_ngfw_status(ngfw_info["ngfw_instance_id"], "pausing")

    # Publish event
    publish_ngfw_event(
        request_id=ngfw_info["ngfw_request_id"],
        instance_id=ngfw_info["instance_uuid"],
        app_id=ngfw_info["app_id"],
        status="pausing",
    )

    # Execute stop plan
    executor = AWSExecutor()
    orchestrator = OpsOrchestrator(executor)
    plan = NGFWStopPlan()

    # Create a simple object with instance_id attribute for get_context
    class InstanceRef:
        def __init__(self, instance_id: str):
            self.instance_id = instance_id

    context = plan.get_context(InstanceRef(ngfw_info["ec2_instance_id"]))
    result = orchestrator.orchestrate(ngfw_info["ec2_instance_id"], plan, context)

    if not result.success:
        error_msg = result.error or "NGFW stop failed"
        logger.error("pause_ngfw_for_range: %s", error_msg)
        _update_ngfw_status(ngfw_info["ngfw_instance_id"], "failed")
        publish_ngfw_event(
            request_id=ngfw_info["ngfw_request_id"],
            instance_id=ngfw_info["instance_uuid"],
            app_id=ngfw_info["app_id"],
            status="failed",
        )
        raise RuntimeError(error_msg)

    # Update status to paused
    _update_ngfw_status(ngfw_info["ngfw_instance_id"], "paused")

    # Publish success event
    publish_ngfw_event(
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

    # Get NGFW info
    ngfw_info = get_range_ngfw_info(request_id)
    if not ngfw_info:
        logger.info("ensure_ngfw_running: no NGFW attached, skipping")
        return

    status = ngfw_info["status"]

    # Already running
    if status == "ready":
        logger.info("ensure_ngfw_running: NGFW already ready, skipping")
        return

    # Failed state - cannot proceed
    if status == "failed":
        raise RuntimeError("NGFW is in failed state, cannot resume range")

    # Resuming - wait for it (another resume may have triggered it)
    if status == "resuming":
        logger.info("ensure_ngfw_running: NGFW is resuming, waiting...")
        # For now, proceed with the start operation which will wait
        # The AWSExecutor.wait_for_running will handle this

    # If pausing, wait for EC2 stop to complete before resuming
    if status == "pausing":
        logger.info("ensure_ngfw_running: NGFW is pausing, waiting for paused...")
        executor = AWSExecutor()
        wait_result = executor.wait_for_stopped(ngfw_info["ec2_instance_id"])
        if not wait_result.success:
            raise RuntimeError(f"NGFW failed to reach paused state: {wait_result.stderr}")
        logger.info("ensure_ngfw_running: NGFW is now paused, proceeding to resume")

    # Paused or pausing - need to resume
    if status in ("paused", "pausing", "resuming"):
        # Update status to resuming
        _update_ngfw_status(ngfw_info["ngfw_instance_id"], "resuming")

        # Publish event
        publish_ngfw_event(
            request_id=ngfw_info["ngfw_request_id"],
            instance_id=ngfw_info["instance_uuid"],
            app_id=ngfw_info["app_id"],
            status="resuming",
        )

        # Execute start plan with retry
        executor = AWSExecutor()
        orchestrator = OpsOrchestrator(executor)
        plan = NGFWStartPlan()

        # Create a simple object with instance_id attribute for get_context
        class InstanceRef:
            def __init__(self, instance_id: str):
                self.instance_id = instance_id

        context = plan.get_context(InstanceRef(ngfw_info["ec2_instance_id"]))

        for attempt in range(NGFW_START_MAX_RETRIES):
            result = orchestrator.orchestrate(ngfw_info["ec2_instance_id"], plan, context)

            if result.success:
                break

            # Last attempt - fail permanently
            if attempt == NGFW_START_MAX_RETRIES - 1:
                error_msg = result.error or "NGFW start failed"
                logger.error("ensure_ngfw_running: %s", error_msg)
                _update_ngfw_status(ngfw_info["ngfw_instance_id"], "failed")
                publish_ngfw_event(
                    request_id=ngfw_info["ngfw_request_id"],
                    instance_id=ngfw_info["instance_uuid"],
                    app_id=ngfw_info["app_id"],
                    status="failed",
                )
                raise RuntimeError(error_msg)

            # Not the last attempt - log, sleep, re-query status, and retry
            delay = NGFW_START_RETRY_DELAYS[attempt]
            logger.warning(
                "ensure_ngfw_running: attempt %d/%d failed, retrying in %ds request_id=%s error=%s",
                attempt + 1,
                NGFW_START_MAX_RETRIES,
                delay,
                request_id,
                result.error,
            )
            time.sleep(delay)

            # Re-query NGFW status before retrying
            refreshed = get_range_ngfw_info(request_id)
            if refreshed and refreshed["status"] == "ready":
                logger.info(
                    "ensure_ngfw_running: NGFW became ready during retry wait, request_id=%s",
                    request_id,
                )
                return

        # Update status to ready
        _update_ngfw_status(ngfw_info["ngfw_instance_id"], "ready")

        # Publish success event
        publish_ngfw_event(
            request_id=ngfw_info["ngfw_request_id"],
            instance_id=ngfw_info["instance_uuid"],
            app_id=ngfw_info["app_id"],
            status="ready",
        )

        logger.info(
            "ensure_ngfw_running: NGFW resumed ec2=%s request_id=%s",
            ngfw_info["ec2_instance_id"],
            request_id,
        )


def _execute_instance_operation(
    executor: AWSExecutor,
    orchestrator: OpsOrchestrator,
    plan: RangePausePlan | RangeResumePlan,
    instance: dict,
) -> tuple[str, bool, str | None]:
    """Execute pause/resume operation on a single instance.

    Args:
        executor: AWSExecutor instance.
        orchestrator: OpsOrchestrator instance.
        plan: Plan to execute (RangePausePlan or RangeResumePlan).
        instance: Dict with uuid, aws_instance_id, role.

    Returns:
        Tuple of (uuid, success, error_message).
    """
    aws_instance_id = instance["aws_instance_id"]
    uuid = instance["uuid"]

    try:
        context = plan.get_context(aws_instance_id)
        result = orchestrator.orchestrate(aws_instance_id, plan, context)

        if result.success:
            logger.info(
                "Operation succeeded for instance %s (uuid=%s)",
                aws_instance_id,
                uuid,
            )
            return (uuid, True, None)
        else:
            error_msg = f"Operation failed: {result.error}"
            logger.error(
                "Operation failed for instance %s (uuid=%s): %s",
                aws_instance_id,
                uuid,
                result.error,
            )
            return (uuid, False, error_msg)

    except Exception as e:
        error_msg = str(e)
        logger.exception(
            "Exception during operation for instance %s (uuid=%s)",
            aws_instance_id,
            uuid,
        )
        return (uuid, False, error_msg)


def run_range_pause(request_id: str) -> None:
    """Pause all instances in a range.

    Stops all EC2 instances belonging to the range in parallel,
    waits for them to reach paused state, then updates the range status.

    Args:
        request_id: UUID string of the Request.

    Raises:
        ValueError: If request not found or no instances.
        Exception: If pause operation fails.
    """
    logger.info("run_range_pause: starting request_id=%s", request_id)

    # Get range data for status updates and events
    range_data = get_range_data_by_request_id(request_id)
    range_id = range_data["range_id"]
    user_id = range_data["user_id"]
    current_status = range_data["status"]

    # Idempotent: if already paused, return success
    if current_status == "paused":
        logger.info("run_range_pause: range already paused, no-op request_id=%s", request_id)
        return

    # Get all instances to pause
    instances = get_range_instance_ids(request_id)

    # Create executor and orchestrator
    executor = AWSExecutor()
    orchestrator = OpsOrchestrator(executor)
    plan = RangePausePlan()

    # Execute stop operations in parallel
    results = []
    with ThreadPoolExecutor(max_workers=len(instances)) as pool:
        futures = {
            pool.submit(
                _execute_instance_operation,
                executor,
                orchestrator,
                plan,
                instance,
            ): instance
            for instance in instances
        }

        for future in as_completed(futures):
            instance = futures[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                logger.exception(
                    "Unexpected error pausing instance %s",
                    instance["aws_instance_id"],
                )
                results.append((instance["uuid"], False, str(e)))

    # Check for failures
    failures = [(uuid, err) for uuid, success, err in results if not success]

    if failures:
        error_msg = f"Failed to pause {len(failures)}/{len(instances)} instances"
        logger.error("run_range_pause: %s", error_msg)

        # Update status to failed
        update_range_status(range_id, "failed", error_message=error_msg)
        publish_status_update(
            request_id=request_id,
            range_id=range_id,
            user_id=user_id,
            new_status="failed",
            error_message=error_msg,
        )
        raise RuntimeError(error_msg)

    # Update instance statuses in database
    _update_instance_statuses(request_id, "paused")

    # Cascade: pause NGFW if no other ranges need it (before reporting paused)
    try:
        pause_ngfw_for_range(request_id, range_data)
    except Exception as e:
        # Non-fatal: log and continue - range instances are already paused
        logger.warning(
            "run_range_pause: NGFW pause failed (non-fatal): %s request_id=%s",
            str(e),
            request_id,
        )

    # Update range status to paused (after NGFW is paused)
    update_range_status(range_id, "paused", paused_at="NOW()")
    publish_status_update(
        request_id=request_id,
        range_id=range_id,
        user_id=user_id,
        new_status="paused",
    )

    logger.info(
        "run_range_pause: completed request_id=%s, paused %d instances",
        request_id,
        len(instances),
    )


def run_range_resume(request_id: str) -> None:
    """Resume all instances in a range.

    Starts all EC2 instances belonging to the range in parallel,
    waits for them to reach running state, then updates the range status.

    Args:
        request_id: UUID string of the Request.

    Raises:
        ValueError: If request not found or no instances.
        Exception: If resume operation fails.
    """
    logger.info("run_range_resume: starting request_id=%s", request_id)

    # Get range data for status updates and events
    range_data = get_range_data_by_request_id(request_id)
    range_id = range_data["range_id"]
    user_id = range_data["user_id"]
    current_status = range_data["status"]

    # Idempotent: if already ready, return success
    if current_status == "ready":
        logger.info("run_range_resume: range already ready, no-op request_id=%s", request_id)
        return

    # Cascade: ensure NGFW is running before resuming range instances
    try:
        ensure_ngfw_running(request_id)
    except Exception as e:
        # Fatal: range cannot resume without NGFW
        error_msg = f"Failed to start NGFW: {e}"
        logger.error("run_range_resume: %s request_id=%s", error_msg, request_id)
        update_range_status(range_id, "failed", error_message=error_msg)
        publish_status_update(
            request_id=request_id,
            range_id=range_id,
            user_id=user_id,
            new_status="failed",
            error_message=error_msg,
        )
        raise RuntimeError(error_msg) from e

    # Get all instances to resume
    instances = get_range_instance_ids(request_id)

    # Create executor and orchestrator
    executor = AWSExecutor()
    orchestrator = OpsOrchestrator(executor)
    plan = RangeResumePlan()

    # Execute start operations in parallel
    results = []
    with ThreadPoolExecutor(max_workers=len(instances)) as pool:
        futures = {
            pool.submit(
                _execute_instance_operation,
                executor,
                orchestrator,
                plan,
                instance,
            ): instance
            for instance in instances
        }

        for future in as_completed(futures):
            instance = futures[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                logger.exception(
                    "Unexpected error resuming instance %s",
                    instance["aws_instance_id"],
                )
                results.append((instance["uuid"], False, str(e)))

    # Check for failures
    failures = [(uuid, err) for uuid, success, err in results if not success]

    if failures:
        error_msg = f"Failed to resume {len(failures)}/{len(instances)} instances"
        logger.error("run_range_resume: %s", error_msg)

        # Update status to failed
        update_range_status(range_id, "failed", error_message=error_msg)
        publish_status_update(
            request_id=request_id,
            range_id=range_id,
            user_id=user_id,
            new_status="failed",
            error_message=error_msg,
        )
        raise RuntimeError(error_msg)

    # Update instance statuses in database
    _update_instance_statuses(request_id, "ready")

    # Update range status to ready
    update_range_status(range_id, "ready", ready_at="NOW()")
    publish_status_update(
        request_id=request_id,
        range_id=range_id,
        user_id=user_id,
        new_status="ready",
    )

    logger.info(
        "run_range_resume: completed request_id=%s, resumed %d instances",
        request_id,
        len(instances),
    )


def _update_instance_statuses(request_id: str, status: str) -> None:
    """Update status for all instances in a range.

    Args:
        request_id: UUID string of the Request.
        status: New status value ('paused' or 'ready').
    """
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE engine_instance
            SET status = %s
            WHERE request_id = (
                SELECT id FROM engine_request WHERE request_id = %s
            )
            """,
            (status, request_id),
        )
        conn.commit()
        logger.debug(
            "_update_instance_statuses: updated %d instances to status=%s",
            cur.rowcount,
            status,
        )
