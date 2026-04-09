"""ECS Fargate task orchestration for Shifter Engine.

This module triggers ECS tasks to provision and teardown range infrastructure.
The Shifter Engine writes directly to RDS, so no callback endpoint is needed.

Local Development:
    Set LOCAL_PROVISIONER=subprocess in settings to run the provisioner locally
    instead of triggering ECS. This requires:
    - AWS credentials configured
    - PROVISIONER_PATH setting pointing to the provisioner directory
"""

from __future__ import annotations

import logging
import os
import subprocess  # nosec B404 - used for local dev provisioner only
from typing import TYPE_CHECKING, Any

from django.conf import settings

from shared.cloud import get_task_runner
from shared.cloud.exceptions import CloudTaskError
from shared.enums import ResourceType

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger(__name__)

_GCP_PROVISIONER_ENV_KEYS = (
    "CLOUD_PROVIDER",
    "ENVIRONMENT",
    "CLOUD_REGION",
    "AWS_REGION",
    "GCP_REGION",
    "GCP_PROJECT_ID",
    "GOOGLE_CLOUD_PROJECT",
    "CLOUD_PROJECT_ID",
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
    "FIELD_ENCRYPTION_KEY",
    "RANGE_EVENTS_TOPIC_ID",
    "SNS_RANGE_EVENTS_ARN",
    "STORAGE_BUCKET_NAME",
    "AGENT_STORAGE_BUCKET",
    "AGENT_S3_BUCKET",
    "RANGE_NETWORK_ID",
    "RANGE_NETWORK_CIDR",
    "RANGE_NETWORK_REGION",
    "PORTAL_NETWORK_CIDRS",
    "RANGE_VPC_ID",
    "RANGE_VPC_CIDR",
    "RANGE_AVAILABILITY_ZONE",
    "AVAILABILITY_ZONE",
)


def _run_local_provisioner(command: list[str]) -> str | None:
    """Run the provisioner locally as a subprocess.

    Args:
        command: Command arguments
            (e.g., ["range", "provision", "--request-id", "..."])

    Returns:
        "local-{pid}" if started successfully, None if not configured

    Raises:
        RuntimeError: If provisioner fails to start
    """
    provisioner_path = getattr(settings, "PROVISIONER_PATH", None)
    if not provisioner_path:
        # Default to relative path from Django app
        base = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        provisioner_path = os.path.join(base, "engine", "provisioner")

    main_py = os.path.join(provisioner_path, "main.py")
    if not os.path.exists(main_py):
        logger.error(f"Provisioner not found at {main_py}")
        return None

    # Build environment for provisioner
    env = os.environ.copy()

    # Ensure required env vars are set (from Django settings or environment)
    env.setdefault("ENVIRONMENT", getattr(settings, "ENVIRONMENT", "dev"))
    env.setdefault("CLOUD_PROVIDER", getattr(settings, "CLOUD_PROVIDER", "aws"))
    env.setdefault("CLOUD_REGION", getattr(settings, "CLOUD_REGION", "us-east-2"))
    env.setdefault("AWS_REGION", getattr(settings, "AWS_REGION", "us-east-2"))
    gcp_project_id = getattr(settings, "GCP_PROJECT_ID", "")
    if gcp_project_id:
        env.setdefault("GCP_PROJECT_ID", gcp_project_id)
        env.setdefault("GOOGLE_CLOUD_PROJECT", gcp_project_id)

    # For local dev, use standard DB connection (not IAM auth)
    # The provisioner will need DB_HOST, DB_USER, DB_PASSWORD, DB_NAME
    if hasattr(settings, "DATABASES"):
        db_config = settings.DATABASES.get("default", {})
        env.setdefault("DB_HOST", str(db_config.get("HOST", "localhost")))
        env.setdefault("DB_PORT", str(db_config.get("PORT", 5432)))
        env.setdefault("DB_USER", str(db_config.get("USER", "postgres")))
        env.setdefault("DB_PASSWORD", str(db_config.get("PASSWORD", "")))
        env.setdefault("DB_NAME", str(db_config.get("NAME", "shifter")))

    # SNS config (for event publishing - LocalStack support)
    sns_arn = getattr(settings, "RANGE_EVENTS_TOPIC_ID", "") or getattr(settings, "SNS_RANGE_EVENTS_ARN", "")
    aws_endpoint = getattr(settings, "AWS_ENDPOINT_URL", "")
    if sns_arn:
        env.setdefault("RANGE_EVENTS_TOPIC_ID", sns_arn)
        env.setdefault("SNS_RANGE_EVENTS_ARN", sns_arn)
    if aws_endpoint:
        env.setdefault("AWS_ENDPOINT_URL", aws_endpoint)

    full_command = ["python", main_py, *command]
    logger.info(f"Starting local provisioner: {' '.join(full_command)}")

    try:
        # Run in background (non-blocking)
        # Security: command is hardcoded path to our provisioner, not user input
        process = subprocess.Popen(  # noqa: S603  # nosec B603
            full_command,
            cwd=provisioner_path,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        logger.info(f"Local provisioner started with PID {process.pid}")
        return f"local-{process.pid}"

    except Exception as e:
        logger.error(f"Failed to start local provisioner: {e}")
        raise RuntimeError(f"Local provisioner failed: {e}") from e


def _is_local_provisioner_enabled() -> bool:
    """Check if local provisioner mode is enabled."""
    mode = getattr(settings, "LOCAL_PROVISIONER", None)
    return mode in ("subprocess", "docker")


def _get_gcp_provisioner_env_overrides() -> dict[str, str] | None:
    """Forward the runtime env contract needed by ephemeral GKE provisioner Jobs."""
    if getattr(settings, "CLOUD_PROVIDER", "aws") != "gcp":
        return None

    fallback_values = {
        "CLOUD_PROVIDER": getattr(settings, "CLOUD_PROVIDER", ""),
        "ENVIRONMENT": getattr(settings, "ENVIRONMENT", ""),
        "CLOUD_REGION": getattr(settings, "CLOUD_REGION", ""),
        "AWS_REGION": getattr(settings, "AWS_REGION", ""),
        "GCP_REGION": os.environ.get("GCP_REGION") or getattr(settings, "CLOUD_REGION", ""),
        "GCP_PROJECT_ID": getattr(settings, "GCP_PROJECT_ID", ""),
        "GOOGLE_CLOUD_PROJECT": getattr(settings, "GCP_PROJECT_ID", ""),
        "CLOUD_PROJECT_ID": getattr(settings, "GCP_PROJECT_ID", ""),
    }

    env_overrides: dict[str, str] = {}
    for key in _GCP_PROVISIONER_ENV_KEYS:
        value = os.environ.get(key)
        if value is None or value == "":
            value = fallback_values.get(key, "")
        if value is None or value == "":
            continue
        env_overrides[key] = str(value)

    return env_overrides or None


def _get_engine_task_config() -> tuple[str, str, dict[str, Any] | None] | None:
    """Read Engine task runner configuration from settings.

    Returns:
        Tuple of (cluster_or_location, task_definition_or_job, network_config)
        or None if configuration is incomplete.
    """
    provider = getattr(settings, "CLOUD_PROVIDER", "aws")
    cluster: str = (
        getattr(settings, "ENGINE_TASK_CLUSTER", None) or getattr(settings, "ENGINE_ECS_CLUSTER_ARN", None) or ""
    )
    task_definition: str = (
        getattr(settings, "ENGINE_TASK_DEFINITION", None) or getattr(settings, "ENGINE_TASK_DEFINITION_ARN", None) or ""
    )

    if provider == "gcp":
        if not all([cluster, task_definition]):
            logger.warning(
                "GCP task configuration incomplete, skipping task run. "
                "Set ENGINE_TASK_NAMESPACE/ENGINE_TASK_CLUSTER and "
                "ENGINE_TASK_IMAGE/ENGINE_TASK_DEFINITION in settings."
            )
            return None
        return cluster, task_definition, None

    security_group_id: str = (
        getattr(settings, "ENGINE_TASK_NETWORK_SECURITY_GROUP_ID", None)
        or getattr(settings, "ENGINE_ECS_SECURITY_GROUP_ID", None)
        or ""
    )
    subnet_ids_str: str = (
        getattr(settings, "ENGINE_TASK_NETWORK_SUBNET_IDS", None)
        or getattr(settings, "ENGINE_PRIVATE_SUBNET_IDS", "")
        or ""
    )

    if not all([cluster, task_definition, security_group_id, subnet_ids_str]):
        logger.warning(
            "AWS task configuration incomplete, skipping ECS task. "
            "Set ENGINE_TASK_CLUSTER, ENGINE_TASK_DEFINITION, "
            "ENGINE_TASK_NETWORK_SECURITY_GROUP_ID, and ENGINE_TASK_NETWORK_SUBNET_IDS in settings."
        )
        return None

    subnet_ids = [s.strip() for s in subnet_ids_str.split(",") if s.strip()]
    if not subnet_ids:
        logger.error("ENGINE_TASK_NETWORK_SUBNET_IDS is empty or invalid")
        return None

    network_config = {
        "awsvpcConfiguration": {
            "subnets": subnet_ids,
            "securityGroups": [security_group_id],
            "assignPublicIp": "DISABLED",
        }
    }
    return cluster, task_definition, network_config


def _start_ecs_task(range_id: int, user_id: int, command: str) -> str | None:
    """Start an ECS Fargate task for provisioning operations.

    Args:
        range_id: Database ID of the Range
        user_id: Django User ID of the User
        command: Command to run ("provision" or "destroy")

    Returns:
        ECS task ARN if successful, None if ECS is not configured

    Raises:
        TypeError: If range_id is not an integer or user_id is not an integer or command is not a string
        ValueError: If range_id is negative or user_id is negative or command is empty
        CloudTaskError: If ECS task fails to start
    """
    if range_id is None or not isinstance(range_id, int):
        raise TypeError("range_id must be an integer")
    if user_id is None or not isinstance(user_id, int):
        raise TypeError("user_id must be an integer")
    if range_id < 0:
        raise ValueError("range_id must be non-negative")
    if user_id < 0:
        raise ValueError("user_id must be non-negative")
    if command is None or not isinstance(command, str):
        raise TypeError("command must be a string")
    if not command.strip():
        raise ValueError("command must be a non-empty string")

    task_config = _get_engine_task_config()
    if task_config is None:
        return None

    cluster, task_definition, network_config = task_config

    logger.info(f"Starting ECS task for range_id={range_id} command={command}")

    command_list = [
        ResourceType.RANGE.value,
        command,
        "--range-id",
        str(range_id),
        "--user-id",
        str(user_id),
    ]

    try:
        runner = get_task_runner()
        task_arn = runner.run_task(
            task_definition=task_definition,
            cluster=cluster,
            command=command_list,
            container_name="pulumi-provisioner",
            env_overrides=_get_gcp_provisioner_env_overrides(),
            network_config=network_config,
        )
        logger.info(f"Started ECS task: range_id={range_id} command={command} task_arn={task_arn}")
        return task_arn
    except CloudTaskError as e:
        logger.error(f"Failed to start ECS task for range_id={range_id}: {e}")
        raise


def start_provisioning(range_id: int, user_id: int) -> str | None:
    """Start provisioning a range via ECS Fargate.

    Args:
        range_id: Database ID of the Range to provision
        user_id: Django User ID of the User
    Returns:
        ECS task ARN if successful, None if ECS is not configured
        (falls back to stub behavior for local dev)

    Raises:
        CloudTaskError: If ECS task fails to start
    """
    return _start_ecs_task(range_id, user_id, "provision")


def start_teardown(range_id: int, user_id: int) -> str | None:
    """Start teardown of a range via ECS Fargate.

    Args:
        range_id: Database ID of the Range to teardown
        user_id: User ID for event publishing in the provisioner

    Returns:
        ECS task ARN if successful, None if ECS is not configured
        (falls back to stub behavior for local dev)

    Raises:
        CloudTaskError: If ECS task fails to start

    .. deprecated::
        Use :func:`start_range_teardown` instead.
    """
    return _start_ecs_task(range_id, user_id, "destroy")


# =============================================================================
# Request-based Range ECS Functions (new pattern matching NGFW)
# =============================================================================


def _start_range_ecs_task(request_id: UUID, command: str) -> str | None:
    """Start an ECS Fargate task for Range operations using request_id.

    Matches NGFW pattern - provisioner fetches all data from DB using request_id.

    Args:
        request_id: UUID of the Request to operate on
        command: Command to run ("provision" or "destroy")

    Returns:
        ECS task ARN if successful, None if ECS is not configured

    Raises:
        TypeError: If request_id is None or not a UUID
        ValueError: If command is invalid
        CloudTaskError: If ECS task fails to start
    """
    from uuid import UUID as UUIDType

    if request_id is None:
        raise TypeError("request_id cannot be None")
    if not isinstance(request_id, UUIDType):
        raise TypeError(f"request_id must be a UUID, got {type(request_id).__name__}")
    valid_commands = ("provision", "destroy", "pause", "resume")
    if command not in valid_commands:
        raise ValueError(f"Invalid command: {command}. Must be one of {valid_commands}.")

    # Check for local provisioner mode first
    if _is_local_provisioner_enabled():
        logger.info(f"Using local provisioner for Range request_id={request_id} command={command}")
        command_list = ["range", command, "--request-id", str(request_id)]
        return _run_local_provisioner(command_list)

    task_config = _get_engine_task_config()
    if task_config is None:
        return None

    cluster, task_definition, network_config = task_config

    command_list = ["range", command, "--request-id", str(request_id)]
    logger.info(f"Starting Range ECS task for request_id={request_id} command={command}")

    try:
        runner = get_task_runner()
        task_arn = runner.run_task(
            task_definition=task_definition,
            cluster=cluster,
            command=command_list,
            container_name="pulumi-provisioner",
            env_overrides=_get_gcp_provisioner_env_overrides(),
            network_config=network_config,
        )
        logger.info(f"Started Range ECS task: request_id={request_id} task_arn={task_arn}")
        return task_arn
    except CloudTaskError as e:
        logger.error(f"Failed to start Range ECS task for request_id={request_id}: {e}")
        raise


def start_range_provisioning(request_id: UUID) -> str | None:
    """Start provisioning a range via ECS Fargate using request_id.

    Args:
        request_id: UUID of the Request to provision.

    Returns:
        ECS task ARN if successful, None if ECS is not configured.

    Raises:
        TypeError: If request_id is None or not a UUID
        CloudTaskError: If ECS task fails to start
    """
    return _start_range_ecs_task(request_id, "provision")


def start_range_teardown(request_id: UUID) -> str | None:
    """Start teardown of a range via ECS Fargate using request_id.

    Args:
        request_id: UUID of the Request to teardown.

    Returns:
        ECS task ARN if successful, None if ECS is not configured.

    Raises:
        TypeError: If request_id is None or not a UUID
        CloudTaskError: If ECS task fails to start
    """
    return _start_range_ecs_task(request_id, "destroy")


def start_range_operation(request_id: UUID, operation: str) -> str | None:
    """Start a range runtime operation (pause/resume) via ECS Fargate.

    Args:
        request_id: UUID of the Request containing the Range.
        operation: Operation to perform ('pause' or 'resume').

    Returns:
        ECS task ARN if successful, None if ECS is not configured.

    Raises:
        TypeError: If request_id is None or not a UUID
        ValueError: If operation is not 'pause' or 'resume'
        CloudTaskError: If ECS task fails to start
    """
    from uuid import UUID as UUIDType

    if request_id is None:
        raise TypeError("request_id cannot be None")
    if not isinstance(request_id, UUIDType):
        raise TypeError(f"request_id must be a UUID, got {type(request_id).__name__}")
    if operation not in ("pause", "resume"):
        raise ValueError(f"Invalid operation: {operation}. Must be 'pause' or 'resume'.")

    return _start_range_ecs_task(request_id, operation)


def _start_ngfw_ecs_task(request_id: UUID, command: list[str]) -> str | None:
    """Start an ECS Fargate task for NGFW operations.

    Args:
        request_id: UUID of the Request to operate on
        command: Command list to run (e.g., ["ngfw", "provision", "--request-id", "..."])

    Returns:
        ECS task ARN if successful, None if ECS is not configured

    Raises:
        TypeError: If request_id is None or command is not a list
        ValueError: If command is empty
        CloudTaskError: If ECS task fails to start
    """
    from uuid import UUID

    if request_id is None:
        raise TypeError("request_id cannot be None")
    if not isinstance(request_id, UUID):
        raise TypeError(f"request_id must be a UUID, got {type(request_id).__name__}")
    if command is None or not isinstance(command, list):
        raise TypeError("command must be a list")
    if not command:
        raise ValueError("command must be a non-empty list")

    # Check for local provisioner mode first
    if _is_local_provisioner_enabled():
        logger.info(f"Using local provisioner for NGFW request_id={request_id} command={command}")
        return _run_local_provisioner(command)

    task_config = _get_engine_task_config()
    if task_config is None:
        return None

    cluster, task_definition, network_config = task_config

    logger.info(f"Starting NGFW ECS task for request_id={request_id} command={command}")

    try:
        runner = get_task_runner()
        task_arn = runner.run_task(
            task_definition=task_definition,
            cluster=cluster,
            command=command,
            container_name="pulumi-provisioner",
            env_overrides=_get_gcp_provisioner_env_overrides(),
            network_config=network_config,
        )
        logger.info(f"Started NGFW ECS task: request_id={request_id} task_arn={task_arn}")
        return task_arn
    except CloudTaskError as e:
        logger.error(f"Failed to start NGFW ECS task for request_id={request_id}: {e}")
        raise


def start_ngfw_provisioning(request_id: UUID) -> str | None:
    """Start provisioning an NGFW via ECS Fargate.

    Args:
        request_id: UUID of the Request to provision.

    Returns:
        ECS task ARN if successful, None if ECS is not configured
        (falls back to stub behavior for local dev)

    Raises:
        TypeError: If request_id is None or not a UUID
        CloudTaskError: If ECS task fails to start
    """
    command = ["ngfw", "provision", "--request-id", str(request_id)]
    return _start_ngfw_ecs_task(request_id, command)


def start_ngfw_teardown(request_id: UUID) -> str | None:
    """Start teardown/deprovision of an NGFW via ECS Fargate.

    Args:
        request_id: UUID of the Request to deprovision.

    Returns:
        ECS task ARN if successful, None if ECS is not configured
        (falls back to stub behavior for local dev)

    Raises:
        TypeError: If request_id is None or not a UUID
        CloudTaskError: If ECS task fails to start
    """
    command = ["ngfw", "deprovision", "--request-id", str(request_id)]
    return _start_ngfw_ecs_task(request_id, command)


def start_ngfw_operation(request_id: UUID, operation: str) -> str | None:
    """Start an NGFW runtime operation (start/stop) via ECS Fargate.

    Args:
        request_id: UUID of the Request containing the NGFW instance.
        operation: Operation to perform ('start' or 'stop').

    Returns:
        ECS task ARN if successful, None if ECS is not configured.

    Raises:
        TypeError: If request_id is None or not a UUID
        ValueError: If operation is not 'start' or 'stop'
        CloudTaskError: If ECS task fails to start
    """
    from uuid import UUID

    if request_id is None:
        raise TypeError("request_id cannot be None")
    if not isinstance(request_id, UUID):
        raise TypeError(f"request_id must be a UUID, got {type(request_id).__name__}")
    if operation not in ("start", "stop"):
        raise ValueError(f"Invalid operation: {operation}. Must be 'start' or 'stop'.")

    command = ["ngfw", operation, "--request-id", str(request_id)]
    return _start_ngfw_ecs_task(request_id, command)


def get_task_status(task_arn: str) -> dict | None:
    """Get the status of an ECS task.

    Args:
        task_arn: ARN of the ECS task to check

    Returns:
        Dict with status info, or None if not configured
    """
    if not task_arn:
        return None

    cluster = getattr(settings, "ENGINE_TASK_CLUSTER", None) or getattr(settings, "ENGINE_ECS_CLUSTER_ARN", None)
    if not cluster:
        return None

    try:
        runner = get_task_runner()
        result = runner.get_task_status(cluster=cluster, task_id=task_arn)

        if result is None:
            return {"status": "UNKNOWN", "reason": "Task not found"}

        return {
            "status": result.get("status", "UNKNOWN"),
            "desired_status": result.get("desired_status"),
            "started_at": result.get("started_at"),
            "stopped_at": result.get("stopped_at"),
            "stopped_reason": result.get("stopped_reason"),
        }
    except CloudTaskError as e:
        logger.error(f"Failed to get task status: {e}")
        return None
