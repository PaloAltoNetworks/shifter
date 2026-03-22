"""ECS task orchestration for experiment execution.

Triggers ECS Fargate tasks to execute experiment scripts on range instances
and collect artifacts. Follows the same pattern as engine.ecs but uses
experiment-specific task definitions.

The experiment executor container:
- Receives commands as JSON via ECS task overrides
- Executes scripts on range instances via SSM
- Uploads output artifacts to S3
- Publishes completion events to the experiments SQS queue
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from django.conf import settings

from shared.cloud import get_task_runner
from shared.cloud.exceptions import CloudTaskError

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger(__name__)


def _get_ecs_config() -> tuple[str, str, str, list[str]] | None:
    """Read ECS configuration from settings.

    Returns:
        Tuple of (cluster_arn, task_def_arn, security_group_id, subnet_ids)
        or None if configuration is incomplete.
    """
    cluster_arn: str = getattr(settings, "ENGINE_ECS_CLUSTER_ARN", "")
    task_def_arn: str = getattr(settings, "EXPERIMENT_TASK_DEFINITION_ARN", "") or getattr(
        settings, "ENGINE_TASK_DEFINITION_ARN", ""
    )
    security_group_id: str = getattr(settings, "ENGINE_ECS_SECURITY_GROUP_ID", "")
    subnet_ids_str: str = getattr(settings, "ENGINE_PRIVATE_SUBNET_IDS", "")

    if not all([cluster_arn, task_def_arn, security_group_id, subnet_ids_str]):
        logger.warning(
            "ECS configuration incomplete for experiment tasks. "
            "Required: ENGINE_ECS_CLUSTER_ARN, EXPERIMENT_TASK_DEFINITION_ARN "
            "(or ENGINE_TASK_DEFINITION_ARN), ENGINE_ECS_SECURITY_GROUP_ID, "
            "ENGINE_PRIVATE_SUBNET_IDS."
        )
        return None

    subnet_ids = [s.strip() for s in subnet_ids_str.split(",") if s.strip()]
    if not subnet_ids:
        logger.error("ENGINE_PRIVATE_SUBNET_IDS is empty or invalid")
        return None

    return cluster_arn, task_def_arn, security_group_id, subnet_ids


def start_experiment_task(
    experiment_id: int,
    run_id: int,
    request_id: UUID,
    command: str,
    payload: dict | None = None,
) -> str | None:
    """Start an ECS Fargate task for experiment execution.

    The task receives the operation type and context via container command
    overrides. The payload (e.g., serialized script commands) is passed
    as a JSON-encoded environment variable.

    Args:
        experiment_id: Database ID of the Experiment.
        run_id: Database ID of the ExperimentRun.
        request_id: UUID of the CMS Request (for range correlation).
        command: Operation to perform ("execute" or "collect").
        payload: Optional JSON-serializable data for the task
            (e.g., list of script commands for "execute").

    Returns:
        ECS task ARN if started successfully, None if ECS is not configured.

    Raises:
        TypeError: If required parameters are None or wrong type.
        ValueError: If command is not a valid operation.
        CloudTaskError: If the ECS RunTask API call fails.
    """
    if experiment_id is None or not isinstance(experiment_id, int):
        raise TypeError(f"experiment_id must be an int, got {type(experiment_id).__name__}")
    if run_id is None or not isinstance(run_id, int):
        raise TypeError(f"run_id must be an int, got {type(run_id).__name__}")
    if request_id is None:
        raise TypeError("request_id cannot be None")
    if command not in ("execute", "collect"):
        raise ValueError(f"Invalid command: {command!r}. Must be 'execute' or 'collect'.")

    ecs_config = _get_ecs_config()
    if ecs_config is None:
        return None

    cluster_arn, task_def_arn, security_group_id, subnet_ids = ecs_config

    # Build container command
    container_command = [
        "experiment",
        command,
        "--experiment-id",
        str(experiment_id),
        "--run-id",
        str(run_id),
        "--request-id",
        str(request_id),
    ]

    # Build environment overrides for payload
    env_overrides: dict[str, str] | None = None
    if payload is not None:
        env_overrides = {"EXPERIMENT_PAYLOAD": json.dumps(payload)}

    logger.info(
        "Starting experiment ECS task: experiment=%d run=%d request_id=%s command=%s",
        experiment_id,
        run_id,
        request_id,
        command,
    )

    network_config = {
        "awsvpcConfiguration": {
            "subnets": subnet_ids,
            "securityGroups": [security_group_id],
            "assignPublicIp": "DISABLED",
        }
    }

    try:
        runner = get_task_runner()
        task_arn = runner.run_task(
            task_definition=task_def_arn,
            cluster=cluster_arn,
            command=container_command,
            container_name="experiment-executor",
            env_overrides=env_overrides,
            network_config=network_config,
        )
        logger.info(
            "Started experiment ECS task: experiment=%d run=%d task_arn=%s",
            experiment_id,
            run_id,
            task_arn,
        )
        return task_arn
    except CloudTaskError:
        logger.exception(
            "Failed to start experiment ECS task: experiment=%d run=%d",
            experiment_id,
            run_id,
        )
        raise
