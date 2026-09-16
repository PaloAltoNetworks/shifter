"""Behavior tests for the provisioner task-status projection (engine.ecs).

Both AWS (EKS) and GCP (GKE) dispatch the provisioner as a Kubernetes Job
(#1826); the runner-level status mapping is covered by the adapter tests
(test_gcp_task_runner.py / test_aws_task_runner.py). This file covers the
engine-level projection in engine/ecs/_status.py: the pure result shaping, the
config gate, and the CloudTaskError swallow. Per ADR-019-R1 it does not patch
first-party seams: the projection is tested directly, the gate needs no mock,
and the swallow is exercised by monkeypatching the Kubernetes API boundary
(the loader the runner uses) to fail, then asserting observable behavior.
"""

import logging

from engine.ecs import get_task_status
from engine.ecs._status import _project_task_status
from shared.cloud.exceptions import CloudTaskError
from shared.cloud.kubernetes._runner import KubernetesTaskRunner


class TestProjectTaskStatus:
    def test_maps_running_task(self) -> None:
        result = _project_task_status({"status": "RUNNING", "desired_status": "RUNNING"})
        assert result["status"] == "RUNNING"
        assert result["desired_status"] == "RUNNING"

    def test_maps_stopped_task_with_reason(self) -> None:
        result = _project_task_status({"status": "STOPPED", "stopped_reason": "Task completed"})
        assert result["status"] == "STOPPED"
        assert result["stopped_reason"] == "Task completed"

    def test_returns_all_expected_keys(self) -> None:
        result = _project_task_status(
            {
                "status": "STOPPED",
                "desired_status": "STOPPED",
                "started_at": "2024-01-01T00:00:00Z",
                "stopped_at": "2024-01-01T01:00:00Z",
                "stopped_reason": "Essential container exited",
            }
        )
        assert set(result) >= {"status", "desired_status", "started_at", "stopped_at", "stopped_reason"}

    def test_none_result_maps_to_unknown_not_found(self) -> None:
        result = _project_task_status(None)
        assert result["status"] == "UNKNOWN"
        assert "not found" in result.get("reason", "").lower()

    def test_defaults_status_to_unknown(self) -> None:
        assert _project_task_status({"task_id": "provisioner-abc123"})["status"] == "UNKNOWN"

    def test_status_is_string_and_optional_fields_default_none(self) -> None:
        result = _project_task_status({"status": "RUNNING"})
        assert isinstance(result["status"], str)
        assert result.get("started_at") is None
        assert result.get("stopped_at") is None
        assert result.get("stopped_reason") is None

    def test_timestamps_pass_through(self) -> None:
        result = _project_task_status(
            {"status": "STOPPED", "started_at": "2024-01-01T00:00:00Z", "stopped_at": "2024-01-01T01:00:00Z"}
        )
        assert result["started_at"] == "2024-01-01T00:00:00Z"
        assert result["stopped_at"] == "2024-01-01T01:00:00Z"


class TestGetTaskStatusConfigGate:
    """The config gate returns None before any provider dispatch."""

    def test_returns_none_when_task_arn_is_none(self) -> None:
        assert get_task_status(None) is None

    def test_returns_none_when_task_arn_is_empty(self) -> None:
        assert get_task_status("") is None

    def test_returns_none_when_cluster_unconfigured(self, aws_ecs_unconfigured) -> None:
        assert get_task_status("provisioner-abc123") is None


class TestGetTaskStatusErrorSwallow:
    def test_returns_none_and_logs_when_runner_boundary_fails(self, aws_ecs_configured, caplog, monkeypatch) -> None:
        # Fail the Kubernetes API boundary the runner loads. get_task_status must
        # swallow the CloudTaskError and return None rather than propagating.
        def _raise(_self):
            raise CloudTaskError("boom")

        monkeypatch.setattr(KubernetesTaskRunner, "_load_kubernetes_api", _raise)
        with caplog.at_level(logging.ERROR, logger="engine.ecs"):
            result = get_task_status("provisioner-abc123")
        assert result is None
        assert "failed" in caplog.text.lower() or "error" in caplog.text.lower()
