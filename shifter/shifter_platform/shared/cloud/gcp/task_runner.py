"""GCP GKE Job task runner adapter implementing TaskRunner protocol.

Replaces AWS ECS Fargate for launching provisioner containers.
On GCP, the provisioner runs as a Kubernetes Job in the GKE cluster.

Authentication:
    - In-cluster: Uses Workload Identity (automatic when running in GKE)
    - Local dev: Uses kubeconfig (~/.kube/config)
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from django.conf import settings

from shared.cloud.exceptions import CloudTaskError

logger = logging.getLogger(__name__)


def _load_kube_config() -> None:
    """Load Kubernetes configuration (in-cluster or kubeconfig)."""
    from kubernetes import config as k8s_config  # type: ignore[import-untyped]

    try:
        k8s_config.load_incluster_config()
        logger.debug("Loaded in-cluster Kubernetes config")
    except k8s_config.ConfigException:
        k8s_config.load_kube_config()
        logger.debug("Loaded kubeconfig from ~/.kube/config")


class GCPTaskRunner:
    """GKE Job task runner implementing TaskRunner protocol."""

    def _get_batch_client(self) -> Any:
        from kubernetes import client as k8s_client  # type: ignore[import-untyped]

        _load_kube_config()
        return k8s_client.BatchV1Api()

    def _get_core_client(self) -> Any:
        from kubernetes import client as k8s_client  # type: ignore[import-untyped]

        _load_kube_config()
        return k8s_client.CoreV1Api()

    def run_task(
        self,
        task_definition: str,
        cluster: str,
        command: list[str],
        container_name: str,
        env_overrides: dict[str, str] | None = None,
        network_config: dict[str, Any] | None = None,
    ) -> str | None:
        """Launch a Kubernetes Job in the GKE cluster.

        Args:
            task_definition: Container image URI (e.g. us-east4-docker.pkg.dev/project/repo/provisioner:latest)
            cluster: Ignored for GKE (cluster is determined by kubeconfig/in-cluster config).
                     Kept for protocol compatibility.
            command: Command arguments for the container.
            container_name: Name for the container in the pod spec.
            env_overrides: Environment variables to set on the container.
            network_config: Optional dict with:
                - namespace: K8s namespace (default: from GKE_PROVISIONER_NAMESPACE setting)
                - service_account: K8s service account (for Workload Identity)

        Returns:
            Job name if created successfully, None on failure.

        Raises:
            CloudTaskError: If the Job fails to create.
        """
        from kubernetes import client as k8s_client  # type: ignore[import-untyped]

        logger.debug(
            "run_task: image=%s command=%s container=%s",
            task_definition,
            command,
            container_name,
        )

        network_config = network_config or {}
        namespace = network_config.get(
            "namespace",
            getattr(settings, "GKE_PROVISIONER_NAMESPACE", "shifter-engine"),
        )
        service_account = network_config.get(
            "service_account",
            getattr(settings, "GKE_PROVISIONER_SERVICE_ACCOUNT", None),
        )

        job_name = f"provisioner-{uuid.uuid4().hex[:12]}"

        env_vars = []
        if env_overrides:
            env_vars = [k8s_client.V1EnvVar(name=k, value=v) for k, v in env_overrides.items()]

        container = k8s_client.V1Container(
            name=container_name,
            image=task_definition,
            command=["python", "main.py"],
            args=command,
            env=env_vars or None,
        )

        pod_spec = k8s_client.V1PodSpec(
            containers=[container],
            restart_policy="Never",
            service_account_name=service_account,
        )

        template = k8s_client.V1PodTemplateSpec(
            metadata=k8s_client.V1ObjectMeta(
                labels={"app": "shifter-provisioner", "job-name": job_name},
            ),
            spec=pod_spec,
        )

        job_spec = k8s_client.V1JobSpec(
            template=template,
            backoff_limit=0,
            ttl_seconds_after_finished=3600,
        )

        job = k8s_client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=k8s_client.V1ObjectMeta(
                name=job_name,
                namespace=namespace,
                labels={"app": "shifter-provisioner"},
            ),
            spec=job_spec,
        )

        try:
            batch_client = self._get_batch_client()
            batch_client.create_namespaced_job(namespace=namespace, body=job)
            logger.info("run_task: created job=%s namespace=%s", job_name, namespace)
            return job_name
        except Exception as e:
            logger.error("run_task: failed to create job=%s error=%s", job_name, e)
            raise CloudTaskError(f"Failed to create GKE Job: {e}") from e

    def get_task_status(self, cluster: str, task_id: str) -> dict[str, Any] | None:
        """Get the status of a Kubernetes Job.

        Args:
            cluster: Ignored (cluster determined by kubeconfig). Kept for protocol compatibility.
            task_id: Job name returned by run_task().

        Returns:
            Dict with status info, or None if job not found.
        """
        logger.debug("get_task_status: task_id=%s", task_id)

        namespace = getattr(settings, "GKE_PROVISIONER_NAMESPACE", "shifter-engine")

        try:
            batch_client = self._get_batch_client()
            job = batch_client.read_namespaced_job(name=task_id, namespace=namespace)
        except Exception as e:
            error_str = str(e)
            if "404" in error_str or "Not Found" in error_str:
                logger.debug("get_task_status: job not found task_id=%s", task_id)
                return None
            logger.error("get_task_status: failed task_id=%s error=%s", task_id, e)
            raise CloudTaskError(f"Failed to get GKE Job status: {e}") from e

        status = job.status
        if status.succeeded and status.succeeded > 0:
            job_status = "STOPPED"
            stopped_reason = "Completed successfully"
        elif status.failed and status.failed > 0:
            job_status = "STOPPED"
            stopped_reason = "Job failed"
        elif status.active and status.active > 0:
            job_status = "RUNNING"
            stopped_reason = None
        else:
            job_status = "PENDING"
            stopped_reason = None

        return {
            "task_id": task_id,
            "status": job_status,
            "desired_status": "STOPPED" if status.succeeded or status.failed else "RUNNING",
            "started_at": status.start_time,
            "stopped_at": status.completion_time,
            "stopped_reason": stopped_reason,
        }
