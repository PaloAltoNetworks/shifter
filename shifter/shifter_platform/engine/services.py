"""Engine service interface.

Infrastructure lifecycle for Shifter platform.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from shared.schemas import RangeContext, RangeSpec
from shared.enums import RangeStatus
from shared.enums import CANCELLABLE_STATUSES, TERMINAL_STATUSES

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from engine.ssh import SSHConnection

logger = logging.getLogger(__name__)


class EngineError(Exception):
    """Base exception for engine service errors."""

    pass


def create_range(request: RangeSpec) -> int:
    """Provision infrastructure for range.

    Creates a Range record, allocates subnet, and triggers ECS provisioning.

    Args:
        request: Validated RangeSpec with scenario, user, and instances.

    Returns:
        range_id: The ID of the created range.

    Raises:
        TypeError: If request is not a RangeSpec
        ValueError: If subnet allocation fails (capacity exhausted)
        User.DoesNotExist: If user_id doesn't map to a Django user
    """
    from django.contrib.auth import get_user_model

    from engine.ecs import start_provisioning
    from engine.models import Range

    User = get_user_model()

    # Validate request type
    if not isinstance(request, RangeSpec):
        raise TypeError(f"request must be RangeSpec, got {type(request).__name__}")

    logger.debug(
        "create_range: scenario=%s user_id=%s instances=%d",
        request.scenario_id,
        request.user_id,
        len(request.instances),
    )

    # Get Django user for FK (required for auth)
    user = User.objects.get(id=request.user_id)

    # Allocate subnet index
    subnet_index = Range.allocate_subnet_index()

    # Create range with full config
    range_obj = Range.objects.create(
        user=user,
        cms_user_id=request.user_id,
        status=Range.Status.PROVISIONING,
        subnet_index=subnet_index,
        range_config=request.model_dump(),
    )

    logger.info(
        "create_range: created range_id=%s subnet_index=%s",
        range_obj.id,
        subnet_index,
    )

    # Trigger ECS provisioning
    task_arn = start_provisioning(range_obj.id, request.user_id)

    if task_arn:
        range_obj.step_function_execution_arn = task_arn
        range_obj.save(update_fields=["step_function_execution_arn"])
        logger.info("create_range: started ECS task=%s", task_arn)

    return range_obj.id


def destroy_range(range_id: int) -> bool:
    """Tear down range infrastructure.

    Sets status to DESTROYING and triggers async ECS teardown.
    Idempotent: returns True if range is already being destroyed.

    Args:
        range_id: The ID of the range to destroy.

    Returns:
        True if range exists and destruction initiated (or already in progress).
        False if range not found or already destroyed.
    """
    from engine.ecs import start_teardown
    from engine.models import Range

    logger.debug("destroy_range: range_id=%s", range_id)

    try:
        range_obj = Range.objects.get(id=range_id)
    except Range.DoesNotExist:
        logger.warning("destroy_range: range not found range_id=%s", range_id)
        return False

    # Already destroyed - nothing to do
    if range_obj.status == Range.Status.DESTROYED:
        logger.warning("destroy_range: range already destroyed range_id=%s", range_id)
        return False

    # Already destroying - idempotent success
    if range_obj.status == Range.Status.DESTROYING:
        logger.info("destroy_range: range already destroying range_id=%s", range_id)
        return True

    # Set status and trigger teardown
    range_obj.status = Range.Status.DESTROYING
    range_obj.save(update_fields=["status"])

    logger.info("destroy_range: set status to DESTROYING range_id=%s", range_id)

    task_arn = start_teardown(range_id, range_obj.cms_user_id)

    if task_arn:
        range_obj.step_function_execution_arn = task_arn
        range_obj.save(update_fields=["step_function_execution_arn"])
        logger.info("destroy_range: started ECS task=%s", task_arn)

    return True


def cancel_range(range_ctx: RangeContext) -> None:
    """Cancel in-progress provisioning.

    Only works for ranges in PENDING or PROVISIONING status.
    Sets status directly to DESTROYED without triggering teardown.

    Note: This does NOT clean up any AWS resources that may have been
    partially created. A proper implementation would signal the provisioner
    to abort and clean up. See GitHub issue for tracking.

    Args:
        range_ctx: RangeContext with range_id and metadata.

    Returns:
        None

    Raises:
        TypeError: If range_ctx is None or not a RangeContext.
        ValueError: If range_ctx.range_id is None or negative.
    """
    # Input validation
    if range_ctx is None:
        logger.error("cancel_range called with None range_ctx")
        raise TypeError("range_ctx cannot be None")

    if not isinstance(range_ctx, RangeContext):
        logger.error(
            "cancel_range called with invalid type: %s",
            type(range_ctx).__name__,
        )
        raise TypeError(
            f"range_ctx must be RangeContext, got {type(range_ctx).__name__}"
        )

    if range_ctx.range_id is None:
        logger.error("cancel_range called with None range_id")
        raise ValueError("range_ctx.range_id cannot be None")

    if not isinstance(range_ctx.range_id, int) or range_ctx.range_id < 0:
        logger.error(
            "cancel_range called with invalid range_id: %s",
            range_ctx.range_id,
        )
        raise ValueError("range_ctx.range_id must be a non-negative integer")

    logger.debug(
        "cancel_range: range_id=%s user_id=%s status=%s",
        range_ctx.range_id,
        range_ctx.user_id,
        range_ctx.status,
    )
    from engine.models import Range

    range_id = range_ctx.range_id

    try:
        range_obj = Range.objects.get(id=range_id)
    except Range.DoesNotExist:
        logger.warning("cancel_range: range not found range_id=%s", range_id)
        return

    if range_ctx.status not in CANCELLABLE_STATUSES:
        logger.warning(
            "cancel_range: range not cancellable range_id=%s status=%s",
            range_id,
            range_ctx.status,
        )
        return

    range_ctx.status = RangeStatus.DESTROYING
    range_obj.status = Range.Status.DESTROYING
    range_obj.save(update_fields=["status"])

    # Provisioner will poll for status and destroy when it sees DESTROYING
    # accept small risk of race condition. TODO: #465

    logger.info("cancel_range: cancelled range_id=%s", range_id)


def get_range_status(range_id: int) -> dict[str, Any] | None:
    """Get current state and instance details.

    Args:
        range_id: The ID of the range.

    Returns:
        Dict with range status info, or None if not found.
        Keys: status, error_message, instances, created_at, ready_at
    """
    from engine.models import Range

    logger.debug("get_range_status: range_id=%s", range_id)

    try:
        range_obj = Range.objects.get(id=range_id)
    except Range.DoesNotExist:
        logger.warning("get_range_status: range not found range_id=%s", range_id)
        return None

    return {
        "status": range_obj.status,
        "error_message": range_obj.error_message,
        "instances": range_obj.provisioned_instances or [],
        "created_at": range_obj.created_at.isoformat() if range_obj.created_at else None,
        "ready_at": range_obj.ready_at.isoformat() if range_obj.ready_at else None,
    }


def pause_range(range_id: int) -> None:
    """Pause range instances."""
    raise NotImplementedError


def resume_range(range_id: int) -> None:
    """Resume range instances."""
    raise NotImplementedError


def connect_terminal(user: User, range_id: int, instance_uuid: str) -> SSHConnection:
    """Get SSH connection to instance.

    Args:
        user: Authenticated user requesting connection
        range_id: ID of the range containing the instance
        instance_uuid: UUID of the instance to connect to

    Returns:
        SSHConnection configured for the instance

    Raises:
        ValueError: If user is None, range_id invalid, instance_uuid invalid,
            range not READY, or instance not found
        PermissionError: If user doesn't own the range
        Range.DoesNotExist: If range not found
    """
    # Lazy imports to avoid circular dependencies
    from engine.models import Range
    from engine.secrets import get_ssh_key
    from engine.ssh import SSHConnection

    # Input validation
    if user is None:
        raise ValueError("user is required")
    if range_id is None or not isinstance(range_id, int) or range_id < 0:
        raise ValueError("range_id must be a positive integer")
    if not instance_uuid:
        raise ValueError("instance_uuid is required")

    logger.debug("connect_terminal: range_id=%s instance_uuid=%s", range_id, instance_uuid)

    # Fetch range
    try:
        range_obj = Range.objects.get(id=range_id)
    except Range.DoesNotExist:
        logger.error("Range not found: range_id=%s", range_id)
        raise

    # Verify ownership
    if range_obj.user.id != user.id:
        logger.error("Permission denied: user=%s does not own range=%s", user.id, range_id)
        raise PermissionError("User does not own this range")

    # Verify range is ready
    if range_obj.status != Range.Status.READY:
        logger.error("Range not ready: range_id=%s status=%s", range_id, range_obj.status)
        raise ValueError(f"Range is not ready (status: {range_obj.status})")

    # Find instance by UUID
    instance = range_obj.get_instance_by_uuid(instance_uuid)
    if instance is None:
        logger.error("Instance not found: range_id=%s instance_uuid=%s", range_id, instance_uuid)
        raise ValueError(f"Instance {instance_uuid} not found in range")

    # Get SSH key from secrets
    ssh_key_arn = instance.get("ssh_key_secret_arn")
    if not ssh_key_arn:
        logger.error("No SSH key ARN for instance: %s", instance_uuid)
        raise ValueError(f"Instance {instance_uuid} has no SSH key configured")

    ssh_key = get_ssh_key(ssh_key_arn)

    # Create SSH connection
    host = instance.get("private_ip")
    if not host:
        logger.error("No IP address for instance: %s", instance_uuid)
        raise ValueError(f"Instance {instance_uuid} has no IP address")

    return SSHConnection(
        host=host,
        username="ubuntu",  # Default, could be enhanced based on OS type
        private_key=ssh_key,
    )
