"""``GCPTaskRunner``: Kubernetes Job implementation of the TaskRunner
protocol.

Split out of the historical monolithic ``task_runner.py`` (#561); the
manifest-building, Job/Secret lifecycle, and status-reading logic live in
sibling private submodules (``_job_manifest``, ``_job_lifecycle``,
``_secrets``, ``_status``, ``_run_task_flow``) and are wired together here.
"""

from __future__ import annotations

import importlib
import logging
import os
from typing import Any

from shared.cloud.exceptions import CloudTaskError
from shared.cloud.gcp.base import parse_job_task_id

from ._run_task_flow import _build_run_context, _run_task
from ._secrets import _build_secret_name as _build_secret_name_impl
from ._status import _build_status_payload, _read_job_status
from ._types import _KubernetesApis

logger = logging.getLogger(__name__)


class GCPTaskRunner:
    """Kubernetes Job implementation of TaskRunner protocol.

    The generic TaskRunner interface remains ECS-shaped in existing call sites.
    For GCP:

    - ``cluster`` is interpreted as the Kubernetes namespace.
    - ``task_definition`` is interpreted as the container image to run.
    - ``command`` is passed as container args so the image ENTRYPOINT is kept.
    """

    @staticmethod
    def _load_kubernetes_api() -> tuple[object, object, object, type[Exception]]:
        try:
            kubernetes = importlib.import_module("kubernetes")
        except ImportError as e:
            raise CloudTaskError("GCP task runner support requires kubernetes") from e

        config = kubernetes.config
        config_exception = getattr(getattr(config, "config_exception", None), "ConfigException", Exception)

        try:
            if os.environ.get("KUBERNETES_SERVICE_HOST"):
                try:
                    config.load_incluster_config()
                except config_exception:
                    config.load_kube_config()
            else:
                config.load_kube_config()
        except Exception as e:
            raise CloudTaskError(f"Failed to load Kubernetes client configuration ({type(e).__name__})") from e

        client = kubernetes.client
        api_exception = getattr(getattr(client, "exceptions", None), "ApiException", Exception)
        return client.BatchV1Api(), client.CoreV1Api(), client, api_exception

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
            raise CloudTaskError("GCP task runner requires a Kubernetes namespace in ENGINE_TASK_CLUSTER")
        if not image:
            raise CloudTaskError("GCP task runner requires a container image in ENGINE_TASK_DEFINITION")

        try:
            apis = _KubernetesApis(*self._load_kubernetes_api())
            context = _build_run_context(
                apis,
                namespace,
                image,
                command,
                container_name,
                env_overrides,
                task_identity,
            )
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
