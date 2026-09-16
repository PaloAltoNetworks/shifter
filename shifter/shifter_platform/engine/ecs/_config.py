"""Engine task-runner configuration projection (Kubernetes Job dispatch).

Reads Django settings into the ``(cluster, task_definition, network_config)``
tuple the task runner needs. Split out of ``engine/ecs.py`` (#685).

Both AWS (EKS) and GCP (GKE) dispatch the provisioner as a Kubernetes Job
(#1826), so ``cluster`` is the Job namespace, ``task_definition`` is the image,
and ``network_config`` is always ``None`` (pod networking is owned by the
cluster, not an awsvpc override). AWS range/target delivery remains ECS/VM behind
the ADR-039 range adapter, which is a separate transport from this
provisioner-dispatch config.
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

# Log under the stable "engine.ecs" namespace (asserted by tests and used in
# dashboards) even though this code now lives in a package submodule.
logger = logging.getLogger("engine.ecs")

_KUBERNETES_TASK_PROVIDERS = frozenset({"aws", "gcp"})


def _get_engine_task_config() -> tuple[str, str, dict[str, Any] | None] | None:
    """Read Engine task runner configuration from settings.

    Returns:
        Tuple of (namespace, image, network_config) or None if configuration is
        incomplete. ``network_config`` is always ``None`` for the Kubernetes Job
        dispatch used by both AWS and GCP.
    """
    provider = settings.CLOUD_PROVIDER
    cluster: str = (
        getattr(settings, "ENGINE_TASK_CLUSTER", None) or getattr(settings, "ENGINE_ECS_CLUSTER_ARN", None) or ""
    )
    task_definition: str = (
        getattr(settings, "ENGINE_TASK_DEFINITION", None) or getattr(settings, "ENGINE_TASK_DEFINITION_ARN", None) or ""
    )

    if provider in _KUBERNETES_TASK_PROVIDERS:
        return _kubernetes_engine_task_config(cluster, task_definition)
    raise ImproperlyConfigured(f"Unsupported CLOUD_PROVIDER for engine task dispatch: {provider!r}")


def _kubernetes_engine_task_config(cluster: str, task_definition: str) -> tuple[str, str, dict[str, Any] | None] | None:
    """Return the Kubernetes engine task config (namespace, image, None), or None when incomplete."""
    if not all([cluster, task_definition]):
        logger.warning(
            "Kubernetes task configuration incomplete, skipping task run. "
            "Set ENGINE_TASK_NAMESPACE/ENGINE_TASK_CLUSTER and "
            "ENGINE_TASK_IMAGE/ENGINE_TASK_DEFINITION in settings."
        )
        return None
    return cluster, task_definition, None
