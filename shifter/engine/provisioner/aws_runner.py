"""AWS runner for NGFW EC2 lifecycle operations.

This module provides simple boto3 wrappers for starting and stopping
NGFW EC2 instances. It replaces the AWSExecutor/OpsOrchestrator pattern
with direct, straightforward API calls.

All functions raise exceptions on failure rather than returning status codes.
"""

import logging

import boto3
from botocore.exceptions import ClientError, WaiterError

logger = logging.getLogger(__name__)

# Default timeouts (seconds)
START_TIMEOUT_DEFAULT = 300  # 5 minutes for instance to start
STOP_TIMEOUT_DEFAULT = 900  # 15 minutes for NGFW graceful shutdown
WAITER_DELAY = 15  # Poll interval for waiters

# Error message constants
_ERR_INSTANCE_ID_REQUIRED = "ec2_instance_id is required"
_ERR_INVALID_INSTANCE_ID = "ec2_instance_id must be a valid AWS instance ID (e.g., 'i-0123456789abcdef0')"


def _validate_instance_id(ec2_instance_id: str) -> None:
    """Validate EC2 instance ID format.

    Args:
        ec2_instance_id: AWS EC2 instance ID to validate

    Raises:
        ValueError: If instance ID is empty or invalid format
    """
    if not ec2_instance_id:
        raise ValueError(_ERR_INSTANCE_ID_REQUIRED)

    if not ec2_instance_id.startswith("i-"):
        raise ValueError(_ERR_INVALID_INSTANCE_ID)


def get_instance_state(ec2_instance_id: str) -> str:
    """Get the current state of an EC2 instance.

    Args:
        ec2_instance_id: AWS EC2 instance ID (e.g., 'i-0123456789abcdef0')

    Returns:
        Instance state string: 'pending', 'running', 'stopping', 'stopped',
        'shutting-down', or 'terminated'

    Raises:
        ValueError: If ec2_instance_id is empty or None
        RuntimeError: If instance not found or API call fails
    """
    _validate_instance_id(ec2_instance_id)

    logger.debug("get_instance_state: ec2_instance_id=%s", ec2_instance_id)

    try:
        ec2 = boto3.client("ec2")
        response = ec2.describe_instances(InstanceIds=[ec2_instance_id])

        reservations = response.get("Reservations", [])
        if not reservations:
            raise RuntimeError(f"Instance not found: {ec2_instance_id}")

        instances = reservations[0].get("Instances", [])
        if not instances:
            raise RuntimeError(f"Instance not found: {ec2_instance_id}")

        state = instances[0].get("State", {}).get("Name", "unknown")
        logger.debug(
            "get_instance_state: ec2_instance_id=%s state=%s",
            ec2_instance_id,
            state,
        )
        return state

    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        error_message = e.response.get("Error", {}).get("Message", str(e))
        logger.error(
            "get_instance_state: failed ec2_instance_id=%s code=%s message=%s",
            ec2_instance_id,
            error_code,
            error_message,
        )
        raise RuntimeError(f"Failed to describe instance {ec2_instance_id}: {error_code}: {error_message}") from e


def start_ngfw(
    ec2_instance_id: str,
    timeout_seconds: int = START_TIMEOUT_DEFAULT,
    wait: bool = True,
) -> None:
    """Start an NGFW EC2 instance.

    This function is idempotent - if the instance is already running or
    starting, it returns immediately without error.

    Args:
        ec2_instance_id: AWS EC2 instance ID (e.g., 'i-0123456789abcdef0')
        timeout_seconds: Maximum time to wait for instance to start (only used if wait=True)
        wait: If True (default), wait for instance to reach running state.
              If False, issue start command and return immediately (fire-and-forget).

    Raises:
        ValueError: If ec2_instance_id is empty or invalid
        RuntimeError: If start fails, instance is terminated/shutting-down,
                      or times out (when wait=True)
    """
    _validate_instance_id(ec2_instance_id)

    logger.info("start_ngfw: starting ec2_instance_id=%s", ec2_instance_id)

    # Check current state first (defensive)
    current_state = get_instance_state(ec2_instance_id)
    logger.debug("start_ngfw: current_state=%s", current_state)

    if current_state == "running":
        logger.info(
            "start_ngfw: instance already running ec2_instance_id=%s",
            ec2_instance_id,
        )
        return

    if current_state == "terminated":
        raise RuntimeError(f"Cannot start terminated instance: {ec2_instance_id}")

    if current_state == "shutting-down":
        raise RuntimeError(f"Cannot start instance that is shutting down: {ec2_instance_id}")

    # Handle transitional states
    ec2 = boto3.client("ec2")

    if current_state == "pending":
        # Already starting
        if wait:
            logger.info("start_ngfw: instance already starting, waiting for running state")
            _wait_for_running(ec2, ec2_instance_id, timeout_seconds)
        else:
            logger.info("start_ngfw: instance already starting (fire-and-forget)")
        return

    if current_state == "stopping":
        # Wait for stopped first, then start
        logger.info("start_ngfw: instance stopping, waiting for stopped state first")
        _wait_for_stopped(ec2, ec2_instance_id, timeout_seconds)
        current_state = "stopped"

    # Start the instance
    if current_state == "stopped":
        try:
            logger.info(
                "start_ngfw: calling start_instances ec2_instance_id=%s",
                ec2_instance_id,
            )
            ec2.start_instances(InstanceIds=[ec2_instance_id])
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.error(
                "start_ngfw: start_instances failed ec2_instance_id=%s code=%s",
                ec2_instance_id,
                error_code,
            )
            raise RuntimeError(f"Failed to start instance {ec2_instance_id}: {error_code}: {error_message}") from e

        # Wait for running state (unless fire-and-forget)
        if wait:
            _wait_for_running(ec2, ec2_instance_id, timeout_seconds)
            logger.info(
                "start_ngfw: instance started successfully ec2_instance_id=%s",
                ec2_instance_id,
            )
        else:
            logger.info(
                "start_ngfw: start command issued (fire-and-forget) ec2_instance_id=%s",
                ec2_instance_id,
            )
    else:
        raise RuntimeError(f"Unexpected instance state '{current_state}' for {ec2_instance_id}")


def stop_ngfw(
    ec2_instance_id: str,
    timeout_seconds: int = STOP_TIMEOUT_DEFAULT,
) -> None:
    """Stop an NGFW EC2 instance and wait for it to be stopped.

    This function is idempotent - if the instance is already stopped,
    it returns immediately. If the instance is in a transitional state,
    it waits for the appropriate stable state first.

    Note: NGFW instances may take longer to stop due to graceful shutdown
    of PAN-OS services. The default timeout is 15 minutes.

    Args:
        ec2_instance_id: AWS EC2 instance ID (e.g., 'i-0123456789abcdef0')
        timeout_seconds: Maximum time to wait for instance to stop

    Raises:
        ValueError: If ec2_instance_id is empty or invalid
        RuntimeError: If stop fails or times out
    """
    _validate_instance_id(ec2_instance_id)

    logger.info("stop_ngfw: stopping ec2_instance_id=%s", ec2_instance_id)

    # Check current state first (defensive)
    current_state = get_instance_state(ec2_instance_id)
    logger.debug("stop_ngfw: current_state=%s", current_state)

    if current_state == "stopped":
        logger.info(
            "stop_ngfw: instance already stopped ec2_instance_id=%s",
            ec2_instance_id,
        )
        return

    if current_state == "terminated":
        raise RuntimeError(f"Cannot stop terminated instance: {ec2_instance_id}")

    if current_state == "shutting-down":
        raise RuntimeError(f"Cannot stop instance that is shutting down: {ec2_instance_id}")

    ec2 = boto3.client("ec2")

    if current_state == "stopping":
        # Already stopping - just wait for stopped
        logger.info("stop_ngfw: instance already stopping, waiting for stopped state")
        _wait_for_stopped(ec2, ec2_instance_id, timeout_seconds)
        return

    if current_state == "pending":
        # Wait for running first, then stop
        logger.info("stop_ngfw: instance starting, waiting for running state first")
        _wait_for_running(ec2, ec2_instance_id, timeout_seconds)
        current_state = "running"

    # Stop the instance
    if current_state == "running":
        try:
            logger.info(
                "stop_ngfw: calling stop_instances ec2_instance_id=%s",
                ec2_instance_id,
            )
            ec2.stop_instances(InstanceIds=[ec2_instance_id])
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.error(
                "stop_ngfw: stop_instances failed ec2_instance_id=%s code=%s",
                ec2_instance_id,
                error_code,
            )
            raise RuntimeError(f"Failed to stop instance {ec2_instance_id}: {error_code}: {error_message}") from e

        # Wait for stopped state
        _wait_for_stopped(ec2, ec2_instance_id, timeout_seconds)
    else:
        raise RuntimeError(f"Unexpected instance state '{current_state}' for {ec2_instance_id}")

    logger.info(
        "stop_ngfw: instance stopped successfully ec2_instance_id=%s",
        ec2_instance_id,
    )


def _wait_for_running(
    ec2: "boto3.client",
    ec2_instance_id: str,
    timeout_seconds: int,
) -> None:
    """Wait for an EC2 instance to reach the 'running' state.

    Args:
        ec2: boto3 EC2 client
        ec2_instance_id: AWS EC2 instance ID
        timeout_seconds: Maximum time to wait

    Raises:
        RuntimeError: If wait times out or fails
    """
    logger.debug(
        "_wait_for_running: waiting for ec2_instance_id=%s timeout=%d",
        ec2_instance_id,
        timeout_seconds,
    )

    try:
        waiter = ec2.get_waiter("instance_running")
        max_attempts = max(1, timeout_seconds // WAITER_DELAY)
        waiter.wait(
            InstanceIds=[ec2_instance_id],
            WaiterConfig={"Delay": WAITER_DELAY, "MaxAttempts": max_attempts},
        )
        logger.info(
            "_wait_for_running: instance is now running ec2_instance_id=%s",
            ec2_instance_id,
        )

    except WaiterError as e:
        logger.error(
            "_wait_for_running: timeout waiting for running state ec2_instance_id=%s",
            ec2_instance_id,
        )
        raise RuntimeError(f"Timeout waiting for instance {ec2_instance_id} to reach running state: {e}") from e

    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        error_message = e.response.get("Error", {}).get("Message", str(e))
        logger.error(
            "_wait_for_running: API error ec2_instance_id=%s code=%s",
            ec2_instance_id,
            error_code,
        )
        raise RuntimeError(f"Failed waiting for instance {ec2_instance_id}: {error_code}: {error_message}") from e


def _wait_for_stopped(
    ec2: "boto3.client",
    ec2_instance_id: str,
    timeout_seconds: int,
) -> None:
    """Wait for an EC2 instance to reach the 'stopped' state.

    Args:
        ec2: boto3 EC2 client
        ec2_instance_id: AWS EC2 instance ID
        timeout_seconds: Maximum time to wait

    Raises:
        RuntimeError: If wait times out or fails
    """
    logger.debug(
        "_wait_for_stopped: waiting for ec2_instance_id=%s timeout=%d",
        ec2_instance_id,
        timeout_seconds,
    )

    try:
        waiter = ec2.get_waiter("instance_stopped")
        max_attempts = max(1, timeout_seconds // WAITER_DELAY)
        waiter.wait(
            InstanceIds=[ec2_instance_id],
            WaiterConfig={"Delay": WAITER_DELAY, "MaxAttempts": max_attempts},
        )
        logger.info(
            "_wait_for_stopped: instance is now stopped ec2_instance_id=%s",
            ec2_instance_id,
        )

    except WaiterError as e:
        logger.error(
            "_wait_for_stopped: timeout waiting for stopped state ec2_instance_id=%s",
            ec2_instance_id,
        )
        raise RuntimeError(f"Timeout waiting for instance {ec2_instance_id} to reach stopped state: {e}") from e

    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        error_message = e.response.get("Error", {}).get("Message", str(e))
        logger.error(
            "_wait_for_stopped: API error ec2_instance_id=%s code=%s",
            ec2_instance_id,
            error_code,
        )
        raise RuntimeError(f"Failed waiting for instance {ec2_instance_id}: {error_code}: {error_message}") from e
