"""Range pause/resume operations.

Handles stopping and starting all EC2 instances in a range.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from events import publish_status_update
from executors.aws_executor import AWSExecutor
from main import get_db_connection, get_range_data_by_request_id, update_range_status
from orchestrators.ops_orchestrator import OpsOrchestrator
from plans.range_pause import RangePausePlan
from plans.range_resume import RangeResumePlan

logger = logging.getLogger(__name__)


def get_range_instance_ids(request_id: str) -> list[dict]:
    """Get all EC2 instance IDs for a range.

    Queries engine_instance records for the given request and extracts
    AWS instance IDs from the state JSON field.

    Args:
        request_id: UUID string of the Request.

    Returns:
        List of dicts with 'uuid' (our instance UUID) and 'aws_instance_id'.

    Raises:
        ValueError: If no instances found or missing AWS instance IDs.
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
    waits for them to reach stopped state, then updates the range status.

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
                    "Unexpected error stopping instance %s",
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

    # Update range status to paused
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
                    "Unexpected error starting instance %s",
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
