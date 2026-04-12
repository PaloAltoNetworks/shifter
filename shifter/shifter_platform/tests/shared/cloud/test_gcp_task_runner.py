"""Tests for the GKE-native GCP task runner."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from shared.cloud.exceptions import CloudTaskError
from shared.cloud.gcp.task_runner import GCPTaskRunner


class _ApiException(Exception):
    def __init__(self, status: int):
        super().__init__(f"status={status}")
        self.status = status


class TestGCPTaskRunnerRunTask:
    """Job creation behavior."""

    def test_creates_namespaced_job(self, settings) -> None:
        settings.ENGINE_TASK_SERVICE_ACCOUNT_NAME = "shifter-provisioner"
        settings.ENGINE_TASK_IMAGE_PULL_POLICY = "Always"
        settings.ENGINE_TASK_BACKOFF_LIMIT = 1
        settings.ENGINE_TASK_TTL_SECONDS_AFTER_FINISHED = 900

        batch_api = MagicMock()
        batch_api.create_namespaced_job.return_value = SimpleNamespace(
            metadata=SimpleNamespace(name="pulumi-provisioner-range-provision-abc123")
        )
        core_api = MagicMock()

        client = SimpleNamespace(
            V1EnvVar=lambda **kwargs: SimpleNamespace(**kwargs),
            V1Container=lambda **kwargs: SimpleNamespace(**kwargs),
            V1PodSpec=lambda **kwargs: SimpleNamespace(**kwargs),
            V1ObjectMeta=lambda **kwargs: SimpleNamespace(**kwargs),
            V1PodTemplateSpec=lambda **kwargs: SimpleNamespace(**kwargs),
            V1JobSpec=lambda **kwargs: SimpleNamespace(**kwargs),
            V1Job=lambda **kwargs: SimpleNamespace(**kwargs),
        )

        runner = GCPTaskRunner()
        runner._load_kubernetes_api = MagicMock(return_value=(batch_api, core_api, client, _ApiException))

        task_id = runner.run_task(
            task_definition="us-central1-docker.pkg.dev/test/provisioner:latest",
            cluster="shifter-jobs",
            command=["range", "provision", "--range-id", "42"],
            container_name="pulumi-provisioner",
            env_overrides={"CLOUD_PROVIDER": "gcp"},
        )

        assert task_id == "shifter-jobs/pulumi-provisioner-range-provision-abc123"
        call_kwargs = batch_api.create_namespaced_job.call_args.kwargs
        assert call_kwargs["namespace"] == "shifter-jobs"
        job = call_kwargs["body"]
        assert job.metadata.generate_name.startswith("pulumi-provisioner-range-provision-")
        assert job.spec.template.spec.service_account_name == "shifter-provisioner"
        assert job.spec.template.spec.containers[0].image == "us-central1-docker.pkg.dev/test/provisioner:latest"
        assert job.spec.template.spec.containers[0].args == ["range", "provision", "--range-id", "42"]
        assert job.spec.template.spec.containers[0].image_pull_policy == "Always"
        assert job.spec.backoff_limit == 1
        assert job.spec.ttl_seconds_after_finished == 900

    def test_requires_namespace(self) -> None:
        runner = GCPTaskRunner()

        with pytest.raises(CloudTaskError, match="namespace"):
            runner.run_task(
                task_definition="image:latest",
                cluster="",
                command=["range", "provision"],
                container_name="pulumi-provisioner",
            )


class TestGCPTaskRunnerGetTaskStatus:
    """Job status mapping behavior."""

    def test_returns_running_status(self) -> None:
        batch_api = MagicMock()
        batch_api.read_namespaced_job_status.return_value = SimpleNamespace(
            status=SimpleNamespace(
                active=1,
                failed=0,
                succeeded=0,
                start_time="2026-04-08T01:02:03Z",
                completion_time=None,
                conditions=[],
            )
        )
        core_api = MagicMock()

        runner = GCPTaskRunner()
        runner._load_kubernetes_api = MagicMock(return_value=(batch_api, core_api, SimpleNamespace(), _ApiException))

        result = runner.get_task_status("shifter-jobs", "shifter-jobs/pulumi-provisioner-range-provision-abc123")

        assert result is not None
        assert result["status"] == "RUNNING"
        assert result["desired_status"] == "RUNNING"
        assert result["task_id"] == "shifter-jobs/pulumi-provisioner-range-provision-abc123"

    def test_returns_succeeded_status(self) -> None:
        batch_api = MagicMock()
        batch_api.read_namespaced_job_status.return_value = SimpleNamespace(
            status=SimpleNamespace(
                active=0,
                failed=0,
                succeeded=1,
                start_time="2026-04-08T01:02:03Z",
                completion_time="2026-04-08T01:05:03Z",
                conditions=[SimpleNamespace(type="Complete", message="Completed successfully", reason="Completed")],
            )
        )
        core_api = MagicMock()

        runner = GCPTaskRunner()
        runner._load_kubernetes_api = MagicMock(return_value=(batch_api, core_api, SimpleNamespace(), _ApiException))

        result = runner.get_task_status("shifter-jobs", "job-abc123")

        assert result is not None
        assert result["status"] == "SUCCEEDED"
        assert result["desired_status"] == "COMPLETED"
        assert result["stopped_reason"] == "Completed successfully"

    def test_returns_failed_status_with_pod_reason(self) -> None:
        batch_api = MagicMock()
        batch_api.read_namespaced_job_status.return_value = SimpleNamespace(
            status=SimpleNamespace(
                active=0,
                failed=1,
                succeeded=0,
                start_time="2026-04-08T01:02:03Z",
                completion_time="2026-04-08T01:05:03Z",
                conditions=[],
            )
        )
        terminated = SimpleNamespace(message="container exited 1", reason="Error")
        pod = SimpleNamespace(
            status=SimpleNamespace(
                container_statuses=[
                    SimpleNamespace(state=SimpleNamespace(terminated=terminated)),
                ]
            )
        )
        core_api = MagicMock()
        core_api.list_namespaced_pod.return_value = SimpleNamespace(items=[pod])

        runner = GCPTaskRunner()
        runner._load_kubernetes_api = MagicMock(return_value=(batch_api, core_api, SimpleNamespace(), _ApiException))

        result = runner.get_task_status("shifter-jobs", "job-abc123")

        assert result is not None
        assert result["status"] == "FAILED"
        assert result["stopped_reason"] == "container exited 1"

    def test_returns_none_on_missing_job(self) -> None:
        batch_api = MagicMock()
        batch_api.read_namespaced_job_status.side_effect = _ApiException(status=404)
        core_api = MagicMock()

        runner = GCPTaskRunner()
        runner._load_kubernetes_api = MagicMock(return_value=(batch_api, core_api, SimpleNamespace(), _ApiException))

        assert runner.get_task_status("shifter-jobs", "job-abc123") is None
