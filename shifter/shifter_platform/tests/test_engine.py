"""Tests for Shifter Engine service (ECS Fargate integration)."""

from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError
from django.test import override_settings


@pytest.fixture
def ecs_settings():
    """Common ECS settings for tests."""
    return {
        "PULUMI_ECS_CLUSTER_ARN": "arn:aws:ecs:us-east-2:123456789012:cluster/test-cluster",
        "PULUMI_TASK_DEFINITION_ARN": "arn:aws:ecs:us-east-2:123456789012:task-definition/test:1",
        "PULUMI_ECS_SECURITY_GROUP_ID": "sg-12345678",
        "PULUMI_PRIVATE_SUBNET_IDS": "subnet-abc123,subnet-def456",
        "AWS_REGION": "us-east-2",
    }


class TestStartProvisioning:
    @override_settings(
        PULUMI_ECS_CLUSTER_ARN="",
        PULUMI_TASK_DEFINITION_ARN="",
        PULUMI_ECS_SECURITY_GROUP_ID="",
        PULUMI_PRIVATE_SUBNET_IDS="",
    )
    def test_returns_none_when_not_configured(self):
        """When ECS config is incomplete, returns None (local dev fallback)."""
        from engine.services.ecs import start_provisioning

        result = start_provisioning(range_id=1)
        assert result is None

    def test_starts_task_and_returns_arn(self, ecs_settings):
        """Successfully starts ECS task."""
        with (
            override_settings(**ecs_settings),
            patch("engine.services.ecs.boto3.client") as mock_client,
        ):
            mock_ecs = mock_client.return_value
            mock_ecs.run_task.return_value = {
                "tasks": [{"taskArn": "arn:aws:ecs:us-east-2:123456789012:task/test/abc123"}],
                "failures": [],
            }

            from engine.services.ecs import start_provisioning

            result = start_provisioning(range_id=42)

            assert result == "arn:aws:ecs:us-east-2:123456789012:task/test/abc123"
            mock_ecs.run_task.assert_called_once()
            call_kwargs = mock_ecs.run_task.call_args.kwargs
            assert call_kwargs["cluster"] == ecs_settings["PULUMI_ECS_CLUSTER_ARN"]
            assert call_kwargs["taskDefinition"] == ecs_settings["PULUMI_TASK_DEFINITION_ARN"]
            assert call_kwargs["launchType"] == "FARGATE"
            # Check command override
            container_overrides = call_kwargs["overrides"]["containerOverrides"][0]
            assert container_overrides["command"] == ["provision", "--range-id", "42"]

    def test_raises_on_client_error(self, ecs_settings):
        """ClientError from AWS is propagated."""
        with (
            override_settings(**ecs_settings),
            patch("engine.services.ecs.boto3.client") as mock_client,
        ):
            mock_ecs = mock_client.return_value
            mock_ecs.run_task.side_effect = ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}},
                "RunTask",
            )

            from engine.services.ecs import start_provisioning

            with pytest.raises(ClientError):
                start_provisioning(range_id=1)

    def test_raises_on_task_start_failure(self, ecs_settings):
        """Raises ClientError when ECS task fails to start."""
        with (
            override_settings(**ecs_settings),
            patch("engine.services.ecs.boto3.client") as mock_client,
        ):
            mock_ecs = mock_client.return_value
            mock_ecs.run_task.return_value = {
                "tasks": [],
                "failures": [{"reason": "RESOURCE:MEMORY", "arn": "arn:..."}],
            }

            from engine.services.ecs import start_provisioning

            with pytest.raises(ClientError) as exc_info:
                start_provisioning(range_id=1)
            assert "TaskStartFailed" in str(exc_info.value)


class TestStartTeardown:
    @override_settings(
        PULUMI_ECS_CLUSTER_ARN="",
        PULUMI_TASK_DEFINITION_ARN="",
        PULUMI_ECS_SECURITY_GROUP_ID="",
        PULUMI_PRIVATE_SUBNET_IDS="",
    )
    def test_returns_none_when_not_configured(self):
        """When ECS config is incomplete, returns None (local dev fallback)."""
        from engine.services.ecs import start_teardown

        result = start_teardown(range_id=1)
        assert result is None

    def test_starts_task_and_returns_arn(self, ecs_settings):
        """Successfully starts ECS teardown task."""
        with (
            override_settings(**ecs_settings),
            patch("engine.services.ecs.boto3.client") as mock_client,
        ):
            mock_ecs = mock_client.return_value
            mock_ecs.run_task.return_value = {
                "tasks": [{"taskArn": "arn:aws:ecs:us-east-2:123456789012:task/test/xyz789"}],
                "failures": [],
            }

            from engine.services.ecs import start_teardown

            result = start_teardown(range_id=99)

            assert result == "arn:aws:ecs:us-east-2:123456789012:task/test/xyz789"
            mock_ecs.run_task.assert_called_once()
            # Check command override for destroy
            container_overrides = mock_ecs.run_task.call_args.kwargs["overrides"]["containerOverrides"][0]
            assert container_overrides["command"] == ["destroy", "--range-id", "99"]

    def test_raises_on_client_error(self, ecs_settings):
        """ClientError from AWS is propagated."""
        with (
            override_settings(**ecs_settings),
            patch("engine.services.ecs.boto3.client") as mock_client,
        ):
            mock_ecs = mock_client.return_value
            mock_ecs.run_task.side_effect = ClientError(
                {"Error": {"Code": "ClusterNotFound", "Message": "Cluster not found"}},
                "RunTask",
            )

            from engine.services.ecs import start_teardown

            with pytest.raises(ClientError):
                start_teardown(range_id=1)


class TestGetTaskStatus:
    @override_settings(AWS_REGION="us-east-2", PULUMI_ECS_CLUSTER_ARN="")
    def test_returns_none_when_cluster_not_configured(self):
        """Returns None when cluster ARN not configured."""
        from engine.services.ecs import get_task_status

        result = get_task_status("arn:aws:ecs:us-east-2:123:task/test/abc")
        assert result is None

    @override_settings(AWS_REGION="us-east-2")
    def test_returns_none_for_empty_arn(self):
        """Returns None when no task ARN provided."""
        from engine.services.ecs import get_task_status

        result = get_task_status("")
        assert result is None

        result = get_task_status(None)
        assert result is None

    def test_returns_status_info(self, ecs_settings):
        """Returns task status info from ECS."""
        from datetime import datetime

        with (
            override_settings(**ecs_settings),
            patch("engine.services.ecs.boto3.client") as mock_client,
        ):
            mock_ecs = mock_client.return_value
            mock_ecs.describe_tasks.return_value = {
                "tasks": [
                    {
                        "taskArn": "arn:aws:ecs:us-east-2:123:task/test/abc",
                        "lastStatus": "RUNNING",
                        "desiredStatus": "RUNNING",
                        "startedAt": datetime(2025, 1, 1, 12, 0, 0),
                        "stoppedAt": None,
                        "stoppedReason": None,
                    }
                ]
            }

            from engine.services.ecs import get_task_status

            arn = "arn:aws:ecs:us-east-2:123:task/test/abc"
            result = get_task_status(arn)

            assert result["status"] == "RUNNING"
            assert result["desired_status"] == "RUNNING"
            assert result["started_at"] == datetime(2025, 1, 1, 12, 0, 0)
            assert result["stopped_at"] is None

    def test_returns_unknown_when_task_not_found(self, ecs_settings):
        """Returns UNKNOWN status when task not found."""
        with (
            override_settings(**ecs_settings),
            patch("engine.services.ecs.boto3.client") as mock_client,
        ):
            mock_ecs = mock_client.return_value
            mock_ecs.describe_tasks.return_value = {"tasks": []}

            from engine.services.ecs import get_task_status

            arn = "arn:aws:ecs:us-east-2:123:task/test/abc"
            result = get_task_status(arn)

            assert result["status"] == "UNKNOWN"
            assert result["reason"] == "Task not found"

    def test_returns_none_on_error(self, ecs_settings):
        """Returns None when describe_tasks fails."""
        with (
            override_settings(**ecs_settings),
            patch("engine.services.ecs.boto3.client") as mock_client,
        ):
            mock_ecs = mock_client.return_value
            mock_ecs.describe_tasks.side_effect = ClientError(
                {"Error": {"Code": "ClusterNotFound", "Message": "Not found"}},
                "DescribeTasks",
            )

            from engine.services.ecs import get_task_status

            arn = "arn:aws:ecs:us-east-2:123:task/test/abc"
            result = get_task_status(arn)
            assert result is None
