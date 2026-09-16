"""``KubernetesTaskRunner``: provider-neutral Kubernetes Job implementation of
the ``shared.cloud.types.TaskRunner`` protocol.

Extracted from the historical GCP-scoped task-runner package (#1824). All
provider-specific wiring — runner label, runtime service account (Workload
Identity vs IRSA), image pull/backoff/TTL settings, and provisioner hardening —
is supplied by an injected ``KubernetesTaskProfile``. Provider adapters (for
example ``shared.cloud.gcp.task_runner.GCPTaskRunner``) build the profile and
compose this runner; this package reads no Django settings and imports no
provider module.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from shared.cloud.exceptions import CloudTaskError

from ._client import load_kubernetes_api
from ._interrupt import interrupt_job
from ._profile import KubernetesTaskProfile
from ._run_task_flow import _build_run_context, _run_task
from ._secrets import _build_secret_name as _build_secret_name_impl
from ._status import _build_status_payload, _read_job_status
from ._types import _KubernetesApis, _TaskLaunchRequest
from .naming import parse_job_task_id

logger = logging.getLogger(__name__)


class KubernetesTaskRunner:
    """Kubernetes Job implementation of the TaskRunner protocol.

    The generic TaskRunner interface remains ECS-shaped in existing call sites:

    - ``cluster`` is interpreted as the Kubernetes namespace.
    - ``task_definition`` is interpreted as the container image to run.
    - ``command`` is passed as container args so the image ENTRYPOINT is kept.
    """

    def __init__(self, profile: KubernetesTaskProfile | Callable[[], KubernetesTaskProfile]) -> None:
        self._profile = profile

    def _resolve_profile(self) -> KubernetesTaskProfile:
        profile = self._profile
        return profile() if callable(profile) else profile

    @staticmethod
    def _load_kubernetes_api() -> tuple[object, object, object, type[Exception]]:
        return load_kubernetes_api()

    @staticmethod
    def _build_secret_name(container_name: str, task_identity: str | None = None) -> str:
        return _build_secret_name_impl(container_name, task_identity)

    def run_task(
        self,
        task_definition: str,
        cluster: str,
        command: list[str],
        container_name: str,
        env_overrides: dict[str, str] | None = None,
        network_config: dict[str, Any] | None = None,
        task_identity: str | None = None,
    ) -> str | None:
        # Networking is handled by the cluster and namespace policies.
        del network_config
        logger.debug("run_task: task_definition=%s cluster=%s", task_definition, cluster)

        namespace = cluster
        image = task_definition
        if not namespace:
            raise CloudTaskError("Kubernetes task runner requires a namespace (cluster)")
        if not image:
            raise CloudTaskError("Kubernetes task runner requires a container image (task definition)")

        try:
            apis = _KubernetesApis(*self._load_kubernetes_api())
            request = _TaskLaunchRequest(
                namespace=namespace,
                image=image,
                command=command,
                container_name=container_name,
                env_overrides=env_overrides,
                task_identity=task_identity,
            )
            context = _build_run_context(apis, request, self._resolve_profile())
            return _run_task(context)
        except CloudTaskError:
            raise
        except Exception as e:
            logger.exception(
                "run_task: failed task_definition=%s error_type=%s",
                task_definition,
                type(e).__name__,
            )
            raise CloudTaskError(f"Failed to create Kubernetes Job ({type(e).__name__})") from e

    def interrupt_task(
        self,
        cluster: str,
        task_ref: str,
        expected_identity: dict[str, Any],
        grace_seconds: int | None = None,
    ) -> str:
        # Kubernetes relies on foreground propagation + pod-absence observation
        # rather than a provider grace period, so grace_seconds is accepted for
        # the provider-neutral seam but not consumed here.
        del grace_seconds
        logger.debug("interrupt_task: cluster=%s task_ref=%s", cluster, task_ref)

        try:
            return interrupt_job(self, cluster, task_ref, expected_identity)
        except CloudTaskError:
            raise
        except Exception as e:
            logger.exception("interrupt_task: failed task_ref=%s error_type=%s", task_ref, type(e).__name__)
            raise CloudTaskError(f"Failed to interrupt Kubernetes Job ({type(e).__name__})") from e

    def get_task_status(self, cluster: str, task_id: str) -> dict[str, Any] | None:
        logger.debug("get_task_status: cluster=%s task_id=%s", cluster, task_id)
        namespace, job_name = parse_job_task_id(task_id, cluster) if task_id else ("", "")
        if not namespace or not job_name:
            return None

        try:
            batch_api, core_api, _client, api_exception = self._load_kubernetes_api()
            job = _read_job_status(batch_api, namespace, job_name, api_exception)
            if job is None:
                return None
            return _build_status_payload(getattr(job, "status", None), core_api, namespace, job_name)
        except CloudTaskError:
            raise
        except Exception as e:
            logger.exception("get_task_status: failed task_id=%s error_type=%s", task_id, type(e).__name__)
            raise CloudTaskError(f"Failed to get Kubernetes Job status ({type(e).__name__})") from e
