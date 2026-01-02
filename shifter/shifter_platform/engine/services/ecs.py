"""ECS Fargate task orchestration for Shifter Engine.

This module triggers ECS tasks to provision and teardown range infrastructure.
The Shifter Engine writes directly to RDS, so no callback endpoint is needed.
"""

import logging

import boto3
from botocore.exceptions import ClientError
from django.conf import settings

logger = logging.getLogger(__name__)


def _get_ecs_client():
    """Get boto3 ECS client."""
    return boto3.client("ecs", region_name=settings.AWS_REGION)


def _start_ecs_task(range_id: int, command: str) -> str | None:
    """Start an ECS Fargate task for provisioning operations.

    Args:
        range_id: Database ID of the Range
        command: Command to run ("provision" or "destroy")

    Returns:
        ECS task ARN if successful, None if ECS is not configured

    Raises:
        ClientError: If ECS task fails to start
    """
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
                        "command": [command, "--range-id", str(range_id)],
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


def start_provisioning(range_id: int) -> str | None:
    """Start provisioning a range via ECS Fargate.

    Args:
        range_id: Database ID of the Range to provision

    Returns:
        ECS task ARN if successful, None if ECS is not configured
        (falls back to stub behavior for local dev)

    Raises:
        ClientError: If ECS task fails to start
    """
    return _start_ecs_task(range_id, "provision")


def start_teardown(range_id: int) -> str | None:
    """Start teardown of a range via ECS Fargate.

    Args:
        range_id: Database ID of the Range to teardown

    Returns:
        ECS task ARN if successful, None if ECS is not configured
        (falls back to stub behavior for local dev)

    Raises:
        ClientError: If ECS task fails to start
    """
    return _start_ecs_task(range_id, "destroy")


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
