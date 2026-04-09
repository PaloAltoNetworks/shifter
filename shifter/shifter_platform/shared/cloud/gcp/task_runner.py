"""GKE-native Kubernetes Job adapter implementing TaskRunner protocol."""

from __future__ import annotations

import importlib
import logging
import os
from typing import Any

from django.conf import settings

from shared.cloud.exceptions import CloudTaskError
from shared.cloud.gcp.base import build_job_generate_name, parse_job_task_id

logger = logging.getLogger(__name__)


class GCPTaskRunner:
    """Kubernetes Job implementation of TaskRunner protocol.

    The generic TaskRunner interface remains ECS-shaped in existing call sites.
    For GCP:

    - ``cluster`` is interpreted as the Kubernetes namespace.
    - ``task_definition`` is interpreted as the container image to run.
    - ``command`` is passed as container args so the image ENTRYPOINT is kept.
    """

    def _load_kubernetes_api(self) -> tuple[Any, Any, Any, type[Exception]]:
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
            raise CloudTaskError(f"Failed to load Kubernetes client configuration: {e}") from e

        client = kubernetes.client
        api_exception = getattr(getattr(client, "exceptions", None), "ApiException", Exception)
        return client.BatchV1Api(), client.CoreV1Api(), client, api_exception

    def _build_env(self, client: Any, env_overrides: dict[str, str] | None) -> list[Any] | None:
        if not env_overrides:
            return None
        return [client.V1EnvVar(name=name, value=value) for name, value in sorted(env_overrides.items())]

    def _build_container(
        self,
        client: Any,
        container_name: str,
        image: str,
        command: list[str],
        env: list[Any] | None,
    ) -> Any:
        return client.V1Container(
            name=container_name,
            image=image,
            args=command,
            env=env,
            image_pull_policy=getattr(settings, "ENGINE_TASK_IMAGE_PULL_POLICY", "IfNotPresent"),
        )

    def _build_job(
        self,
        client: Any,
        namespace: str,
        image: str,
        container_name: str,
        command: list[str],
        env: list[Any] | None,
    ) -> Any:
        pod_spec = client.V1PodSpec(
            containers=[self._build_container(client, container_name, image, command, env)],
            restart_policy="Never",
        )

        service_account_name = getattr(settings, "ENGINE_TASK_SERVICE_ACCOUNT_NAME", "")
        if service_account_name:
            pod_spec.service_account_name = service_account_name

        metadata = client.V1ObjectMeta(
            generate_name=build_job_generate_name(container_name, command),
            labels={
                "app.kubernetes.io/part-of": "shifter",
                "app.kubernetes.io/component": container_name[:63],
                "shifter.dev/task-runner": "gcp",
            },
            annotations={
                "shifter.dev/task-image": image,
            },
        )

        template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(
                labels={
                    "app.kubernetes.io/part-of": "shifter",
                    "app.kubernetes.io/component": container_name[:63],
                }
            ),
            spec=pod_spec,
        )

        spec = client.V1JobSpec(
            template=template,
            backoff_limit=getattr(settings, "ENGINE_TASK_BACKOFF_LIMIT", 0),
            ttl_seconds_after_finished=getattr(settings, "ENGINE_TASK_TTL_SECONDS_AFTER_FINISHED", 3600),
        )

        return client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=metadata,
            spec=spec,
        )

    def _extract_stopped_reason(self, core_api: Any, namespace: str, job_name: str) -> str | None:
        try:
            pods = core_api.list_namespaced_pod(namespace=namespace, label_selector=f"job-name={job_name}")
        except Exception:
            logger.debug("get_task_status: failed to list pods for job=%s", job_name, exc_info=True)
            return None

        for pod in getattr(pods, "items", []):
            container_statuses = getattr(getattr(pod, "status", None), "container_statuses", None) or []
            for container_status in container_statuses:
                state = getattr(container_status, "state", None)
                terminated = getattr(state, "terminated", None)
                if terminated:
                    return getattr(terminated, "message", None) or getattr(terminated, "reason", None)
        return None

    def run_task(
        self,
        task_definition: str,
        cluster: str,
        command: list[str],
        container_name: str,
        env_overrides: dict[str, str] | None = None,
        network_config: dict[str, Any] | None = None,
    ) -> str | None:
        del network_config  # Networking is handled by the cluster and namespace policies.
        logger.debug("run_task: task_definition=%s cluster=%s", task_definition, cluster)

        namespace = cluster
        image = task_definition
        if not namespace:
            raise CloudTaskError("GCP task runner requires a Kubernetes namespace in ENGINE_TASK_CLUSTER")
        if not image:
            raise CloudTaskError("GCP task runner requires a container image in ENGINE_TASK_DEFINITION")

        try:
            batch_api, _core_api, client, _api_exception = self._load_kubernetes_api()
            env = self._build_env(client, env_overrides)
            job = self._build_job(client, namespace, image, container_name, command, env)
            created = batch_api.create_namespaced_job(namespace=namespace, body=job)
            job_name = getattr(getattr(created, "metadata", None), "name", None)
            if not job_name:
                raise CloudTaskError("Kubernetes API did not return a Job name")
            task_id = f"{namespace}/{job_name}"
            logger.info("run_task: started job=%s image=%s", task_id, image)
            return task_id
        except CloudTaskError:
            raise
        except Exception as e:
            logger.error("run_task: failed task_definition=%s error=%s", task_definition, e)
            raise CloudTaskError(f"Failed to create Kubernetes Job: {e}") from e

    def get_task_status(self, cluster: str, task_id: str) -> dict[str, Any] | None:
        logger.debug("get_task_status: cluster=%s task_id=%s", cluster, task_id)
        if not task_id:
            return None

        namespace, job_name = parse_job_task_id(task_id, cluster)
        if not namespace or not job_name:
            return None

        try:
            batch_api, core_api, _client, api_exception = self._load_kubernetes_api()
            try:
                job = batch_api.read_namespaced_job_status(name=job_name, namespace=namespace)
            except api_exception as e:
                if getattr(e, "status", None) == 404:
                    return None
                raise

            status = getattr(job, "status", None)
            active = int(getattr(status, "active", 0) or 0)
            failed = int(getattr(status, "failed", 0) or 0)
            succeeded = int(getattr(status, "succeeded", 0) or 0)
            started_at = getattr(status, "start_time", None)
            stopped_at = getattr(status, "completion_time", None)
            stopped_reason = None

            conditions = list(getattr(status, "conditions", None) or [])
            if conditions:
                for condition in conditions:
                    if getattr(condition, "type", "") in {"Failed", "Complete"}:
                        stopped_reason = getattr(condition, "message", None) or getattr(condition, "reason", None)
                        break

            if succeeded > 0:
                state = "SUCCEEDED"
            elif failed > 0:
                state = "FAILED"
            elif active > 0:
                state = "RUNNING"
            else:
                state = "SUBMITTED"

            if state in {"SUCCEEDED", "FAILED"} and not stopped_reason:
                stopped_reason = self._extract_stopped_reason(core_api, namespace, job_name)

            return {
                "task_id": f"{namespace}/{job_name}",
                "status": state,
                "desired_status": "RUNNING" if state in {"SUBMITTED", "RUNNING"} else "COMPLETED",
                "started_at": started_at,
                "stopped_at": stopped_at,
                "stopped_reason": stopped_reason,
            }
        except CloudTaskError:
            raise
        except Exception as e:
            logger.error("get_task_status: failed task_id=%s error=%s", task_id, e)
            raise CloudTaskError(f"Failed to get Kubernetes Job status: {e}") from e
