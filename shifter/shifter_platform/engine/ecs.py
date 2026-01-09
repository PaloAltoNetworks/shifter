"""ECS Fargate task orchestration for Shifter Engine.

This module triggers ECS tasks to provision and teardown range infrastructure.
The Shifter Engine writes directly to RDS, so no callback endpoint is needed.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import boto3
from botocore.exceptions import ClientError
from django.conf import settings

from shared.enums import ResourceType

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger(__name__)


def _get_ecs_client():
    """Get boto3 ECS client."""
    from botocore.client import BaseClient

    region = settings.AWS_REGION
    if not region:
        logger.error("AWS_REGION is not configured")
        raise ValueError("AWS_REGION is required")

    try:
        client = boto3.client("ecs", region_name=region)
    except Exception:
        logger.error(f"Failed to create ECS client for region {region}")
        raise

    if not isinstance(client, BaseClient):
        logger.error(f"Invalid ECS client returned: {type(client)}")
        raise TypeError(f"Expected BaseClient, got {type(client)}")

    logger.debug(f"Created ECS client for region {region}")
    return client


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
        ClientError: If ECS task fails to start
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

    cluster_arn = getattr(settings, "PULUMI_ECS_CLUSTER_ARN", None)
    task_definition_arn = getattr(settings, "PULUMI_TASK_DEFINITION_ARN", None)
    security_group_id = getattr(settings, "PULUMI_ECS_SECURITY_GROUP_ID", None)
    subnet_ids_str = getattr(settings, "PULUMI_PRIVATE_SUBNET_IDS", "")

    if not all([cluster_arn, task_definition_arn, security_group_id, subnet_ids_str]):
        logger.warning(
            "ECS configuration incomplete, skipping ECS task. "
            "Set PULUMI_ECS_CLUSTER_ARN, PULUMI_TASK_DEFINITION_ARN, "
            "PULUMI_ECS_SECURITY_GROUP_ID, and PULUMI_PRIVATE_SUBNET_IDS in settings."
        )
        return None

    # Parse subnet IDs (comma-separated string)
    subnet_ids = [s.strip() for s in subnet_ids_str.split(",") if s.strip()]

    if not subnet_ids:
        logger.error("PULUMI_PRIVATE_SUBNET_IDS is empty or invalid")
        return None

    logger.info(f"Starting ECS task for range_id={range_id} command={command}")

    ecs = _get_ecs_client()

    try:
        response = ecs.run_task(
            cluster=cluster_arn,
            taskDefinition=task_definition_arn,
            launchType="FARGATE",
            networkConfiguration={
                "awsvpcConfiguration": {
                    "subnets": subnet_ids,
                    "securityGroups": [security_group_id],
                    "assignPublicIp": "DISABLED",
                }
            },
            overrides={
                "containerOverrides": [
                    {
                        "name": "pulumi-provisioner",
                        "command": [
                            ResourceType.RANGE.value,
                            command,
                            "--range-id",
                            str(range_id),
                            "--user-id",
                            str(user_id),
                        ],
                    }
                ]
            },
        )

        # Check if task was started successfully
        if not response.get("tasks"):
            failures = response.get("failures", [])
            failure_reasons = [f.get("reason", "unknown") for f in failures]
            logger.error(f"ECS task failed to start: {failure_reasons}")
            raise ClientError(
                {"Error": {"Code": "TaskStartFailed", "Message": str(failure_reasons)}},
                "RunTask",
            )

        task_arn = response["tasks"][0]["taskArn"]
        logger.info(f"Started ECS task: range_id={range_id} command={command} task_arn={task_arn}")
        return task_arn

    except ClientError as e:
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
        ClientError: If ECS task fails to start
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
        ClientError: If ECS task fails to start
    """
    return _start_ecs_task(range_id, user_id, "destroy")


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
        ClientError: If ECS task fails to start
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

    cluster_arn = getattr(settings, "PULUMI_ECS_CLUSTER_ARN", None)
    task_definition_arn = getattr(settings, "PULUMI_TASK_DEFINITION_ARN", None)
    security_group_id = getattr(settings, "PULUMI_ECS_SECURITY_GROUP_ID", None)
    subnet_ids_str = getattr(settings, "PULUMI_PRIVATE_SUBNET_IDS", "")

    if not all([cluster_arn, task_definition_arn, security_group_id, subnet_ids_str]):
        logger.warning(
            "ECS configuration incomplete, skipping NGFW ECS task. "
            "Set PULUMI_ECS_CLUSTER_ARN, PULUMI_TASK_DEFINITION_ARN, "
            "PULUMI_ECS_SECURITY_GROUP_ID, and PULUMI_PRIVATE_SUBNET_IDS in settings."
        )
        return None

    # Parse subnet IDs (comma-separated string)
    subnet_ids = [s.strip() for s in subnet_ids_str.split(",") if s.strip()]

    if not subnet_ids:
        logger.error("PULUMI_PRIVATE_SUBNET_IDS is empty or invalid")
        return None

    logger.info(f"Starting NGFW ECS task for request_id={request_id} command={command}")

    ecs = _get_ecs_client()

    try:
        response = ecs.run_task(
            cluster=cluster_arn,
            taskDefinition=task_definition_arn,
            launchType="FARGATE",
            networkConfiguration={
                "awsvpcConfiguration": {
                    "subnets": subnet_ids,
                    "securityGroups": [security_group_id],
                    "assignPublicIp": "DISABLED",
                }
            },
            overrides={
                "containerOverrides": [
                    {
                        "name": "pulumi-provisioner",
                        "command": command,
                    }
                ]
            },
        )

        # Check if task was started successfully
        if not response.get("tasks"):
            failures = response.get("failures", [])
            failure_reasons = [f.get("reason", "unknown") for f in failures]
            logger.error(f"NGFW ECS task failed to start: {failure_reasons}")
            raise ClientError(
                {"Error": {"Code": "TaskStartFailed", "Message": str(failure_reasons)}},
                "RunTask",
            )

        task_arn = response["tasks"][0]["taskArn"]
        logger.info(f"Started NGFW ECS task: request_id={request_id} task_arn={task_arn}")
        return task_arn

    except ClientError as e:
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
        ClientError: If ECS task fails to start
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
        ClientError: If ECS task fails to start
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
        ClientError: If ECS task fails to start
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

    cluster_arn = getattr(settings, "PULUMI_ECS_CLUSTER_ARN", None)
    if not cluster_arn:
        return None

    ecs = _get_ecs_client()

    try:
        response = ecs.describe_tasks(cluster=cluster_arn, tasks=[task_arn])

        if not response.get("tasks"):
            return {"status": "UNKNOWN", "reason": "Task not found"}

        task = response["tasks"][0]
        return {
            "status": task.get("lastStatus", "UNKNOWN"),
            "desired_status": task.get("desiredStatus"),
            "started_at": task.get("startedAt"),
            "stopped_at": task.get("stoppedAt"),
            "stopped_reason": task.get("stoppedReason"),
        }
    except ClientError as e:
        logger.error(f"Failed to get task status: {e}")
        return None
