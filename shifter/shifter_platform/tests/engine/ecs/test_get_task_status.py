"""Behavior tests for get_task_status().

Drives the real status-lookup path with AWS configured via settings and the ECS
client mocked at the ``boto3`` boundary (``describe_tasks``). Asserts the mapped
status dict and the error-swallowing behavior, instead of patching
``get_task_runner``.
"""

import logging
from contextlib import contextmanager
from unittest.mock import patch

from botocore.exceptions import ClientError

from .conftest import CLUSTER, make_ecs_client


def _describe(**task_fields):
    """Build a boto3 describe_tasks response wrapping one task."""
    return {"tasks": [task_fields]} if task_fields else {"tasks": []}


@contextmanager
def _boto3_client(client):
    with patch("boto3.client", return_value=client):
        yield


class TestGetTaskStatusSuccess:
    def test_maps_running_task(self, aws_ecs_configured):
        from engine.ecs import get_task_status

        client = make_ecs_client(describe_response=_describe(lastStatus="RUNNING", desiredStatus="RUNNING"))
        with _boto3_client(client):
            result = get_task_status("arn:aws:ecs:task/abc123")
        assert result["status"] == "RUNNING"
        assert result["desired_status"] == "RUNNING"

    def test_maps_stopped_task_with_reason(self, aws_ecs_configured):
        from engine.ecs import get_task_status

        client = make_ecs_client(
            describe_response=_describe(lastStatus="STOPPED", desiredStatus="STOPPED", stoppedReason="Task completed")
        )
        with _boto3_client(client):
            result = get_task_status("arn:aws:ecs:task/abc123")
        assert result["status"] == "STOPPED"
        assert result["stopped_reason"] == "Task completed"

    def test_returns_all_expected_keys(self, aws_ecs_configured):
        from engine.ecs import get_task_status

        client = make_ecs_client(
            describe_response=_describe(
                taskArn="arn:aws:ecs:task/abc123",
                lastStatus="STOPPED",
                desiredStatus="STOPPED",
                startedAt="2024-01-01T00:00:00Z",
                stoppedAt="2024-01-01T01:00:00Z",
                stoppedReason="Essential container exited",
            )
        )
        with _boto3_client(client):
            result = get_task_status("arn:aws:ecs:task/abc123")
        assert set(result) >= {"status", "desired_status", "started_at", "stopped_at", "stopped_reason"}

    def test_queries_configured_cluster_and_task(self, aws_ecs_configured):
        from engine.ecs import get_task_status

        client = make_ecs_client(describe_response=_describe(lastStatus="RUNNING"))
        task_arn = "arn:aws:ecs:us-east-2:123456789:task/test/abc123"
        with _boto3_client(client):
            get_task_status(task_arn)
        client.describe_tasks.assert_called_once_with(cluster=CLUSTER, tasks=[task_arn])


class TestGetTaskStatusMissingInputs:
    def test_returns_none_when_cluster_unconfigured(self, aws_ecs_unconfigured):
        from engine.ecs import get_task_status

        assert get_task_status("arn:aws:ecs:task/abc123") is None

    def test_returns_none_when_task_arn_is_none(self):
        from engine.ecs import get_task_status

        assert get_task_status(None) is None

    def test_returns_none_when_task_arn_is_empty(self):
        from engine.ecs import get_task_status

        assert get_task_status("") is None


class TestGetTaskStatusCloudErrors:
    def test_returns_unknown_when_task_not_found(self, aws_ecs_configured):
        from engine.ecs import get_task_status

        client = make_ecs_client(describe_response=_describe())  # empty tasks
        with _boto3_client(client):
            result = get_task_status("arn:aws:ecs:task/nonexistent")
        assert result["status"] == "UNKNOWN"
        assert "not found" in result.get("reason", "").lower()

    def test_returns_none_and_logs_on_cloud_error(self, aws_ecs_configured, caplog):
        from engine.ecs import get_task_status

        client = make_ecs_client()
        client.describe_tasks.side_effect = ClientError(
            {"Error": {"Code": "ClusterNotFoundException", "Message": "Cluster not found"}}, "DescribeTasks"
        )
        with caplog.at_level(logging.ERROR, logger="engine.ecs"), _boto3_client(client):
            result = get_task_status("arn:aws:ecs:task/abc123")
        assert result is None
        assert "failed" in caplog.text.lower() or "error" in caplog.text.lower()


class TestGetTaskStatusOutputShape:
    def test_status_is_string(self, aws_ecs_configured):
        from engine.ecs import get_task_status

        client = make_ecs_client(describe_response=_describe(lastStatus="RUNNING"))
        with _boto3_client(client):
            result = get_task_status("arn:aws:ecs:task/abc123")
        assert isinstance(result["status"], str)

    def test_timestamps_pass_through(self, aws_ecs_configured):
        from engine.ecs import get_task_status

        client = make_ecs_client(
            describe_response=_describe(
                lastStatus="STOPPED", startedAt="2024-01-01T00:00:00Z", stoppedAt="2024-01-01T01:00:00Z"
            )
        )
        with _boto3_client(client):
            result = get_task_status("arn:aws:ecs:task/abc123")
        assert result["started_at"] == "2024-01-01T00:00:00Z"
        assert result["stopped_at"] == "2024-01-01T01:00:00Z"

    def test_missing_optional_fields_are_none(self, aws_ecs_configured):
        from engine.ecs import get_task_status

        client = make_ecs_client(describe_response=_describe(lastStatus="RUNNING"))
        with _boto3_client(client):
            result = get_task_status("arn:aws:ecs:task/abc123")
        assert result["status"] == "RUNNING"
        assert result.get("started_at") is None
        assert result.get("stopped_at") is None
        assert result.get("stopped_reason") is None

    def test_defaults_status_to_unknown(self, aws_ecs_configured):
        from engine.ecs import get_task_status

        # A task with no lastStatus maps to UNKNOWN.
        client = make_ecs_client(describe_response=_describe(taskArn="arn:aws:ecs:task/abc123"))
        with _boto3_client(client):
            result = get_task_status("arn:aws:ecs:task/abc123")
        assert result["status"] == "UNKNOWN"

    def test_multiple_calls_are_independent(self, aws_ecs_configured):
        from engine.ecs import get_task_status

        client = make_ecs_client()
        client.describe_tasks.return_value = _describe(lastStatus="RUNNING")
        with _boto3_client(client):
            result1 = get_task_status("arn:aws:ecs:task/task1")
            client.describe_tasks.return_value = _describe(lastStatus="STOPPED")
            result2 = get_task_status("arn:aws:ecs:task/task2")
        assert result1["status"] == "RUNNING"
        assert result2["status"] == "STOPPED"
