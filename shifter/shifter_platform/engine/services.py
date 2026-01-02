"""Engine service interface.

Infrastructure lifecycle for Shifter platform.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from shared.schemas import RangeRequest

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from engine.ssh import SSHConnection

logger = logging.getLogger(__name__)


def create_range(request: RangeRequest) -> int:
    """Provision infrastructure for range.

    Args:
        request: Validated RangeRequest with scenario, user, and instances.

    Returns:
        range_id: The ID of the created range.
    """
    raise NotImplementedError


def destroy_range(range_id: int) -> None:
    """Tear down range infrastructure."""
    raise NotImplementedError


def cancel_range(range_id: int) -> None:
    """Cancel in-progress provisioning."""
    raise NotImplementedError


def get_range_status(range_id: int) -> dict[str, Any]:
    """Get current state, progress, instances.

    Returns:
        Dict with keys: status, progress, message, instances
    """
    raise NotImplementedError


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
