"""Engine services package.

Exposes the engine service interface for infrastructure lifecycle.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


def create_range(range_config: dict[str, Any]) -> int:
    """Provision infrastructure for range.

    Args:
        range_config: Fully resolved configuration dict containing
            user_id, instance_config, and optional agent_id from CMS hydrator.

    Returns:
        range_id: The ID of the created range.

    Raises:
        TypeError: If range_config is None or not a dict
        ValueError: If required fields are missing from range_config
        ValueError: If no subnet indices available
        DatabaseError: If Range creation fails
        ClientError: If ECS task fails to start
    """
    from django.contrib.auth import get_user_model

    from engine.models import Range
    from engine.services import ecs

    # Input validation - range_config
    if range_config is None:
        logger.error("create_range called with None range_config")
        raise TypeError("range_config cannot be None")

    if not isinstance(range_config, dict):
        logger.error("create_range called with invalid range_config type: %s", type(range_config).__name__)
        raise TypeError(f"range_config must be a dict, got {type(range_config).__name__}")

    # Validate required fields
    user_id = range_config.get("user_id")
    if user_id is None:
        logger.error("create_range called with missing user_id in range_config")
        raise ValueError("user_id is required in range_config")

    instance_config = range_config.get("instance_config")
    if instance_config is None:
        logger.error("create_range called with missing instance_config in range_config")
        raise ValueError("instance_config is required in range_config")

    logger.debug("create_range called with user_id=%s", user_id)

    try:
        # Allocate subnet index
        subnet_index = Range.allocate_subnet_index()
        logger.debug("create_range allocated subnet_index=%s", subnet_index)

        # Get optional fields
        agent_id = range_config.get("agent_id")
        dc_agent_id = range_config.get("dc_agent_id")

        # Get the user object
        User = get_user_model()
        user = User.objects.get(id=user_id)

        # Create Range record with PENDING status
        range_obj = Range.objects.create(
            user=user,
            agent_id=agent_id,
            dc_agent_id=dc_agent_id,
            status=Range.Status.PENDING,
            subnet_index=subnet_index,
            instance_config=instance_config,
            provisioner_version="v2",
        )

        logger.debug("create_range created range_id=%s with subnet_index=%s", range_obj.id, subnet_index)

        # Start ECS provisioning task
        task_arn = ecs.start_provisioning(range_obj.id)
        logger.debug("create_range started ECS task for range_id=%s, task_arn=%s", range_obj.id, task_arn)

        return range_obj.id

    except ValueError as e:
        logger.error("create_range failed: subnet allocation error - %s", e)
        raise
    except Exception:
        logger.exception("Error in create_range")
        raise


def destroy_range(range_id: int) -> None:
    """Tear down range infrastructure.

    Args:
        range_id: ID of the range to destroy

    Returns:
        None

    Raises:
        TypeError: If range_id is None or not an int
        ValueError: If range_id is negative or range is already destroyed/destroying
        Range.DoesNotExist: If range not found
        ClientError: If ECS teardown fails
    """
    from engine.models import Range
    from engine.services import ecs

    # Input validation
    if range_id is None:
        logger.error("destroy_range called with None range_id")
        raise TypeError("range_id cannot be None")

    if not isinstance(range_id, int):
        logger.error("destroy_range called with invalid range_id type: %s", type(range_id).__name__)
        raise TypeError(f"range_id must be an int, got {type(range_id).__name__}")

    if range_id < 0:
        logger.error("destroy_range called with negative range_id=%s", range_id)
        raise ValueError("range_id must be non-negative")

    logger.debug("destroy_range called for range_id=%s", range_id)

    try:
        range_obj = Range.objects.get(id=range_id)

        # Validate state - can't destroy already destroyed or destroying ranges
        if range_obj.status in (Range.Status.DESTROYED, Range.Status.DESTROYING):
            logger.error(
                "destroy_range: range_id=%s is already %s",
                range_id,
                range_obj.status,
            )
            raise ValueError(f"Range is already {range_obj.status}")

        # Update status to DESTROYING
        range_obj.status = Range.Status.DESTROYING
        range_obj.save()

        logger.debug("destroy_range: updated range_id=%s status to DESTROYING", range_id)

        # Start ECS teardown task
        task_arn = ecs.start_teardown(range_id)
        logger.debug("destroy_range: started ECS teardown for range_id=%s, task_arn=%s", range_id, task_arn)

        return None

    except Range.DoesNotExist:
        logger.error("destroy_range: range_id=%s not found", range_id)
        raise
    except ValueError:
        raise
    except Exception:
        logger.exception("Error in destroy_range for range_id=%s", range_id)
        raise


def cancel_range(range_id: int) -> None:
    """Cancel in-progress provisioning.

    Can only cancel ranges in PENDING or PROVISIONING state.
    Sets the range status to FAILED.

    Args:
        range_id: ID of the range to cancel

    Returns:
        None

    Raises:
        TypeError: If range_id is None or not an int
        ValueError: If range_id is negative or range cannot be cancelled
        Range.DoesNotExist: If range not found
    """
    from engine.models import Range

    # Input validation
    if range_id is None:
        logger.error("cancel_range called with None range_id")
        raise TypeError("range_id cannot be None")

    if not isinstance(range_id, int):
        logger.error("cancel_range called with invalid range_id type: %s", type(range_id).__name__)
        raise TypeError(f"range_id must be an int, got {type(range_id).__name__}")

    if range_id < 0:
        logger.error("cancel_range called with negative range_id=%s", range_id)
        raise ValueError("range_id must be non-negative")

    logger.debug("cancel_range called for range_id=%s", range_id)

    try:
        range_obj = Range.objects.get(id=range_id)

        # Validate state - can only cancel PENDING or PROVISIONING ranges
        if range_obj.status not in Range.CANCELLABLE_STATUSES:
            logger.error(
                "cancel_range: range_id=%s with status=%s cannot be cancelled",
                range_id,
                range_obj.status,
            )
            raise ValueError(f"Range with status {range_obj.status} cannot be cancelled")

        # Update status to FAILED
        range_obj.status = Range.Status.FAILED
        range_obj.error_message = "Cancelled by user"
        range_obj.save()

        logger.debug("cancel_range: set range_id=%s status to FAILED", range_id)

        return None

    except Range.DoesNotExist:
        logger.error("cancel_range: range_id=%s not found", range_id)
        raise
    except ValueError:
        raise
    except Exception:
        logger.exception("Error in cancel_range for range_id=%s", range_id)
        raise


def get_range_status(range_id: int) -> dict[str, Any]:
    """Get current state of range.

    Args:
        range_id: ID of the range to query

    Returns:
        Dict with keys: range_id, status

    Raises:
        TypeError: If range_id is None or wrong type
        ValueError: If range_id is negative
        Range.DoesNotExist: If range not found
    """
    from engine.models import Range

    # Input validation
    if range_id is None:
        logger.error("get_range_status called with None range_id")
        raise TypeError("range_id cannot be None")

    if not isinstance(range_id, int):
        logger.error("get_range_status called with invalid range_id type: %s", type(range_id).__name__)
        raise TypeError(f"range_id must be an int, got {type(range_id).__name__}")

    if range_id < 0:
        logger.error("get_range_status called with negative range_id=%s", range_id)
        raise ValueError("range_id must be non-negative")

    logger.debug("get_range_status called for range_id=%s", range_id)

    try:
        range_obj = Range.objects.get(id=range_id)

        logger.debug("get_range_status returning status=%s for range_id=%s", range_obj.status, range_id)

        return {
            "range_id": range_obj.id,
            "status": range_obj.status,
        }

    except Range.DoesNotExist:
        logger.error("get_range_status: range_id=%s not found", range_id)
        raise
    except Exception:
        logger.exception("Error in get_range_status for range_id=%s", range_id)
        raise


def pause_range(range_id: int) -> None:
    """Pause range instances."""
    raise NotImplementedError("pause_range not yet implemented")


def resume_range(range_id: int) -> None:
    """Resume range instances."""
    raise NotImplementedError("resume_range not yet implemented")


def connect_terminal(user: User, range_id: int, instance_type: str) -> Any:
    """Get SSH connection to instance.

    Args:
        user: The requesting user (must own the range)
        range_id: ID of the range to connect to
        instance_type: Role of instance to connect to (e.g., 'attacker', 'victim')

    Returns:
        SSHConnection: Configured but not yet connected SSH connection

    Raises:
        TypeError: If user, range_id, or instance_type is None or wrong type
        ValueError: If range_id is negative, instance_type is empty, or range not ready
        PermissionError: If user doesn't own the range
        Range.DoesNotExist: If range not found
    """
    from engine.models import Range
    from engine.services.secrets import get_ssh_key
    from engine.services.ssh import SSHConnection

    # Input validation - user
    if user is None:
        logger.error("connect_terminal called with None user")
        raise TypeError("user cannot be None")

    # Input validation - range_id
    if range_id is None:
        logger.error("connect_terminal called with None range_id")
        raise TypeError("range_id cannot be None")

    if not isinstance(range_id, int):
        logger.error("connect_terminal called with invalid range_id type: %s", type(range_id).__name__)
        raise TypeError(f"range_id must be an int, got {type(range_id).__name__}")

    if range_id < 0:
        logger.error("connect_terminal called with negative range_id=%s", range_id)
        raise ValueError("range_id must be non-negative")

    # Input validation - instance_type
    if instance_type is None:
        logger.error("connect_terminal called with None instance_type")
        raise TypeError("instance_type cannot be None")

    if not instance_type:
        logger.error("connect_terminal called with empty instance_type")
        raise ValueError("instance_type cannot be empty")

    logger.debug(
        "connect_terminal called for user_id=%s, range_id=%s, instance_type=%s",
        user.id,
        range_id,
        instance_type,
    )

    try:
        range_obj = Range.objects.get(id=range_id)

        # Verify ownership
        if range_obj.user.id != user.id:
            logger.error(
                "connect_terminal: user_id=%s does not own range_id=%s (owned by %s)",
                user.id,
                range_id,
                range_obj.user.id,
            )
            raise PermissionError("User does not own this range")

        # Verify range is ready
        if range_obj.status != Range.Status.READY:
            logger.error(
                "connect_terminal: range_id=%s is not ready (status=%s)",
                range_id,
                range_obj.status,
            )
            raise ValueError(f"Range is not ready (status={range_obj.status})")

        # Get instance details
        instance = range_obj.get_instance_by_role(instance_type)
        if instance is None:
            logger.error(
                "connect_terminal: instance type '%s' not found in range_id=%s",
                instance_type,
                range_id,
            )
            raise ValueError(f"instance type '{instance_type}' not found in range")

        # Get SSH key from secrets
        ssh_key_arn = instance.get("ssh_key_secret_arn")
        private_key = get_ssh_key(ssh_key_arn)

        # Create SSH connection (not connected yet)
        host = instance.get("private_ip")
        username = instance.get("username", "root")

        logger.debug(
            "connect_terminal: returning SSHConnection for %s@%s (range_id=%s, role=%s)",
            username,
            host,
            range_id,
            instance_type,
        )

        return SSHConnection(
            host=host,
            username=username,
            private_key=private_key,
        )

    except Range.DoesNotExist:
        logger.error("connect_terminal: range_id=%s not found", range_id)
        raise
    except PermissionError:
        raise
    except ValueError:
        raise
    except Exception:
        logger.exception("Error in connect_terminal for range_id=%s", range_id)
        raise
