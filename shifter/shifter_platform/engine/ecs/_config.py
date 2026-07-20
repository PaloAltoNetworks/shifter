"""Engine task-runner configuration projection (AWS ECS / GCP Job).

Reads Django settings into the ``(cluster, task_definition, network_config)``
tuple the task runner needs. Split out of ``engine/ecs.py`` (#685).
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

# Log under the stable "engine.ecs" namespace (asserted by tests and used in
# dashboards) even though this code now lives in a package submodule.
logger = logging.getLogger("engine.ecs")


def _get_engine_task_config() -> tuple[str, str, dict[str, Any] | None] | None:
    """Read Engine task runner configuration from settings.

    Returns:
        Tuple of (cluster_or_location, task_definition_or_job, network_config)
        or None if configuration is incomplete.
    """
    provider = settings.CLOUD_PROVIDER
    cluster: str = (
        getattr(settings, "ENGINE_TASK_CLUSTER", None) or getattr(settings, "ENGINE_ECS_CLUSTER_ARN", None) or ""
    )
    task_definition: str = (
        getattr(settings, "ENGINE_TASK_DEFINITION", None) or getattr(settings, "ENGINE_TASK_DEFINITION_ARN", None) or ""
    )

    if provider == "gcp":
        return _gcp_engine_task_config(cluster, task_definition)
    if provider == "aws":
        return _aws_engine_task_config(cluster, task_definition)
    raise ImproperlyConfigured(f"Unsupported CLOUD_PROVIDER for engine task dispatch: {provider!r}")


def _gcp_engine_task_config(cluster: str, task_definition: str) -> tuple[str, str, dict[str, Any] | None] | None:
    """Return the GCP engine task config, or None when it is incomplete."""
    if not all([cluster, task_definition]):
        logger.warning(
            "GCP task configuration incomplete, skipping task run. "
            "Set ENGINE_TASK_NAMESPACE/ENGINE_TASK_CLUSTER and "
            "ENGINE_TASK_IMAGE/ENGINE_TASK_DEFINITION in settings."
        )
        return None
    return cluster, task_definition, None


def _aws_engine_task_config(cluster: str, task_definition: str) -> tuple[str, str, dict[str, Any] | None] | None:
    """Return the AWS engine task config (cluster, task def, network), or None when incomplete."""
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
