"""AWS ECS Fargate adapter implementing TaskRunner protocol."""

from __future__ import annotations

import logging
import os
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

from shared.cloud.exceptions import CloudTaskError

logger = logging.getLogger(__name__)


class AWSTaskRunner:
    """ECS Fargate implementation of TaskRunner protocol."""

    def _get_client(self) -> Any:
        region: str = str(getattr(settings, "CLOUD_REGION", None) or getattr(settings, "AWS_REGION", "us-east-2"))
        endpoint_url: str | None = os.environ.get("AWS_ENDPOINT_URL") or None
        return boto3.client("ecs", region_name=region, endpoint_url=endpoint_url)

    def run_task(
        self,
        task_definition: str,
        cluster: str,
        command: list[str],
        container_name: str,
        env_overrides: dict[str, str] | None = None,
        network_config: dict[str, Any] | None = None,
    ) -> str | None:
        logger.debug(
            "run_task: task_definition=%s cluster=%s command=%s container=%s",
            task_definition,
            cluster,
            command,
            container_name,
        )
        try:
            client = self._get_client()
            container_overrides: dict[str, Any] = {"command": command}
            if env_overrides:
                container_overrides["environment"] = [{"name": k, "value": v} for k, v in env_overrides.items()]

            kwargs: dict[str, Any] = {
                "taskDefinition": task_definition,
                "cluster": cluster,
                "launchType": "FARGATE",
                "overrides": {
                    "containerOverrides": [
                        {
                            "name": container_name,
                            **container_overrides,
                        }
                    ]
                },
            }
            if network_config:
                kwargs["networkConfiguration"] = network_config

            response: dict[str, Any] = client.run_task(**kwargs)
        except (ClientError, BotoCoreError) as e:
            logger.error("run_task: failed definition=%s error=%s", task_definition, e)
            raise CloudTaskError(f"Failed to run ECS task: {e}") from e

        tasks: list[dict[str, Any]] = response.get("tasks", [])
        if tasks:
            task_arn: str | None = tasks[0].get("taskArn")
            logger.info("run_task: started task_arn=%s", task_arn)
            return task_arn
        failures = response.get("failures", [])
        failure_reasons = [f.get("reason", "unknown") for f in failures]
        raise CloudTaskError(f"No tasks started for {task_definition}: {failure_reasons}")

    def get_task_status(self, cluster: str, task_id: str) -> dict[str, Any] | None:
        logger.debug("get_task_status: cluster=%s task_id=%s", cluster, task_id)
        try:
            client = self._get_client()
            response: dict[str, Any] = client.describe_tasks(cluster=cluster, tasks=[task_id])
            tasks: list[dict[str, Any]] = response.get("tasks", [])
            if not tasks:
                logger.debug("get_task_status: task not found task_id=%s", task_id)
                return None
            task: dict[str, Any] = tasks[0]
            return {
                "task_id": task.get("taskArn"),
                "status": task.get("lastStatus", "UNKNOWN"),
                "desired_status": task.get("desiredStatus"),
                "started_at": task.get("startedAt"),
                "stopped_at": task.get("stoppedAt"),
                "stopped_reason": task.get("stoppedReason"),
            }
        except (ClientError, BotoCoreError) as e:
            logger.error("get_task_status: failed task_id=%s error=%s", task_id, e)
            raise CloudTaskError(f"Failed to get ECS task status: {e}") from e
