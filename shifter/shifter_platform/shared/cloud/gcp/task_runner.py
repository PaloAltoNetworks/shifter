"""GCP GKE Job task runner adapter (stub).

Will replace AWS ECS Fargate for launching provisioner containers.
On GCP, the provisioner runs as a Kubernetes Job in the GKE cluster.
"""

from __future__ import annotations

from typing import Any

from shared.cloud.exceptions import CloudProviderNotImplementedError


class GCPTaskRunner:
    """GKE Job task runner — stub, not yet implemented."""

    def run_task(
        self,
        task_definition: str,
        cluster: str,
        command: list[str],
        container_name: str,
        env_overrides: dict[str, str] | None = None,
        network_config: dict[str, Any] | None = None,
    ) -> str | None:
        raise CloudProviderNotImplementedError("gcp")

    def get_task_status(self, cluster: str, task_id: str) -> dict[str, Any] | None:
        raise CloudProviderNotImplementedError("gcp")
