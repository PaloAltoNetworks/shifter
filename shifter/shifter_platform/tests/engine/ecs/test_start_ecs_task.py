"""Tests for _start_ecs_task() function."""

import logging
from unittest.mock import MagicMock, patch

import pytest

from shared.cloud.exceptions import CloudTaskError


class TestStartEcsTaskSuccess:
    """Successful ECS task start tests."""

    def test_returns_task_arn_on_success(self, settings):
        """Function returns ECS task ARN when task starts successfully."""
        from engine.ecs import _start_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.ENGINE_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.ENGINE_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.ENGINE_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.ENGINE_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        with patch("engine.ecs.get_task_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.run_task.return_value = "arn:aws:ecs:us-east-2:123456789:task/test/abc123"
            mock_get_runner.return_value = mock_runner

            result = _start_ecs_task(range_id=42, user_id=7, command="provision")

            assert result == "arn:aws:ecs:us-east-2:123456789:task/test/abc123"

    def test_calls_run_task_with_correct_parameters(self, settings):
        """Function calls TaskRunner.run_task with correct configuration."""
        from engine.ecs import _start_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.ENGINE_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.ENGINE_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.ENGINE_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.ENGINE_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        with patch("engine.ecs.get_task_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.run_task.return_value = "arn:aws:ecs:us-east-2:123456789:task/test/abc123"
            mock_get_runner.return_value = mock_runner

            _start_ecs_task(range_id=42, user_id=7, command="provision")

            mock_runner.run_task.assert_called_once()
            call_kwargs = mock_runner.run_task.call_args[1]
            assert call_kwargs["cluster"] == "arn:aws:ecs:us-east-2:123456789:cluster/test"
            assert call_kwargs["task_definition"] == "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
            assert call_kwargs["container_name"] == "pulumi-provisioner"

    def test_passes_range_id_user_id_and_command_to_container(self, settings):
        """Function passes resource type, command, range_id, and user_id to container command."""
        from engine.ecs import _start_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.ENGINE_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.ENGINE_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.ENGINE_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.ENGINE_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        with patch("engine.ecs.get_task_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.run_task.return_value = "arn:aws:ecs:us-east-2:123456789:task/test/abc123"
            mock_get_runner.return_value = mock_runner

            _start_ecs_task(range_id=99, user_id=7, command="destroy")

            call_kwargs = mock_runner.run_task.call_args[1]
            # Verify exact command format: ["range", "destroy", "--range-id", "99", "--user-id", "7"]
            assert call_kwargs["command"] == ["range", "destroy", "--range-id", "99", "--user-id", "7"]


class TestStartEcsTaskConfigurationValidation:
    """Configuration validation tests for ECS task start."""

    def test_returns_none_when_cluster_arn_missing(self, settings):
        """Function returns None when ENGINE_ECS_CLUSTER_ARN is not set."""
        from engine.ecs import _start_ecs_task

        settings.AWS_REGION = "us-east-2"
        if hasattr(settings, "ENGINE_ECS_CLUSTER_ARN"):
            delattr(settings, "ENGINE_ECS_CLUSTER_ARN")
        settings.ENGINE_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.ENGINE_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.ENGINE_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        result = _start_ecs_task(range_id=42, user_id=7, command="provision")

        assert result is None

    def test_returns_none_when_task_definition_missing(self, settings):
        """Function returns None when ENGINE_TASK_DEFINITION_ARN is not set."""
        from engine.ecs import _start_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.ENGINE_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        if hasattr(settings, "ENGINE_TASK_DEFINITION_ARN"):
            delattr(settings, "ENGINE_TASK_DEFINITION_ARN")
        settings.ENGINE_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.ENGINE_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        result = _start_ecs_task(range_id=42, user_id=7, command="provision")

        assert result is None

    def test_returns_none_when_security_group_missing(self, settings):
        """Function returns None when ENGINE_ECS_SECURITY_GROUP_ID is not set."""
        from engine.ecs import _start_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.ENGINE_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.ENGINE_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        if hasattr(settings, "ENGINE_ECS_SECURITY_GROUP_ID"):
            delattr(settings, "ENGINE_ECS_SECURITY_GROUP_ID")
        settings.ENGINE_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        result = _start_ecs_task(range_id=42, user_id=7, command="provision")

        assert result is None

    def test_returns_none_when_subnet_ids_missing(self, settings):
        """Function returns None when ENGINE_PRIVATE_SUBNET_IDS is not set."""
        from engine.ecs import _start_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.ENGINE_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.ENGINE_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.ENGINE_ECS_SECURITY_GROUP_ID = "sg-12345678"
        if hasattr(settings, "ENGINE_PRIVATE_SUBNET_IDS"):
            delattr(settings, "ENGINE_PRIVATE_SUBNET_IDS")

        result = _start_ecs_task(range_id=42, user_id=7, command="provision")

        assert result is None

    def test_returns_none_when_subnet_ids_empty(self, settings):
        """Function returns None when ENGINE_PRIVATE_SUBNET_IDS is empty string."""
        from engine.ecs import _start_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.ENGINE_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.ENGINE_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.ENGINE_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.ENGINE_PRIVATE_SUBNET_IDS = ""

        result = _start_ecs_task(range_id=42, user_id=7, command="provision")

        assert result is None

    def test_returns_none_when_subnet_ids_whitespace(self, settings):
        """Function returns None when ENGINE_PRIVATE_SUBNET_IDS is only whitespace."""
        from engine.ecs import _start_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.ENGINE_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.ENGINE_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.ENGINE_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.ENGINE_PRIVATE_SUBNET_IDS = "   ,   ,   "

        result = _start_ecs_task(range_id=42, user_id=7, command="provision")

        assert result is None


class TestStartEcsTaskInputValidation:
    """Input validation tests for ECS task start."""

    def test_raises_when_range_id_is_none(self, settings):
        """Function raises error when range_id is None."""
        from engine.ecs import _start_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.ENGINE_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.ENGINE_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.ENGINE_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.ENGINE_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        with pytest.raises((TypeError, ValueError)):
            _start_ecs_task(range_id=None, user_id=7, command="provision")

    def test_raises_when_range_id_is_negative(self, settings):
        """Function raises error when range_id is negative."""
        from engine.ecs import _start_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.ENGINE_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.ENGINE_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.ENGINE_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.ENGINE_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        with pytest.raises((TypeError, ValueError)):
            _start_ecs_task(range_id=-1, user_id=7, command="provision")

    def test_raises_when_range_id_is_string(self, settings):
        """Function raises error when range_id is a string."""
        from engine.ecs import _start_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.ENGINE_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.ENGINE_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.ENGINE_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.ENGINE_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        with pytest.raises((TypeError, ValueError)):
            _start_ecs_task(range_id="42", user_id=7, command="provision")

    def test_raises_when_user_id_is_none(self, settings):
        """Function raises error when user_id is None."""
        from engine.ecs import _start_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.ENGINE_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.ENGINE_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.ENGINE_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.ENGINE_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        with pytest.raises((TypeError, ValueError)):
            _start_ecs_task(range_id=42, user_id=None, command="provision")

    def test_raises_when_user_id_is_negative(self, settings):
        """Function raises error when user_id is negative."""
        from engine.ecs import _start_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.ENGINE_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.ENGINE_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.ENGINE_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.ENGINE_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        with pytest.raises((TypeError, ValueError)):
            _start_ecs_task(range_id=42, user_id=-1, command="provision")

    def test_raises_when_user_id_is_string(self, settings):
        """Function raises error when user_id is a string."""
        from engine.ecs import _start_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.ENGINE_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.ENGINE_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.ENGINE_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.ENGINE_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        with pytest.raises((TypeError, ValueError)):
            _start_ecs_task(range_id=42, user_id="7", command="provision")

    def test_raises_when_command_is_none(self, settings):
        """Function raises error when command is None."""
        from engine.ecs import _start_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.ENGINE_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.ENGINE_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.ENGINE_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.ENGINE_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        with pytest.raises((TypeError, ValueError)):
            _start_ecs_task(range_id=42, user_id=7, command=None)

    def test_raises_when_command_is_empty(self, settings):
        """Function raises error when command is empty string."""
        from engine.ecs import _start_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.ENGINE_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.ENGINE_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.ENGINE_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.ENGINE_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        with pytest.raises((TypeError, ValueError)):
            _start_ecs_task(range_id=42, user_id=7, command="")


class TestStartEcsTaskCloudErrors:
    """Cloud error tests for ECS task start."""

    def test_raises_cloud_task_error_when_run_task_fails(self, settings):
        """Function raises CloudTaskError when TaskRunner.run_task fails."""
        from engine.ecs import _start_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.ENGINE_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.ENGINE_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.ENGINE_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.ENGINE_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        with patch("engine.ecs.get_task_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.run_task.side_effect = CloudTaskError("Cluster not found")
            mock_get_runner.return_value = mock_runner

            with pytest.raises(CloudTaskError):
                _start_ecs_task(range_id=42, user_id=7, command="provision")

    def test_raises_cloud_task_error_when_no_tasks_returned(self, settings):
        """Function raises CloudTaskError when adapter reports no tasks started."""
        from engine.ecs import _start_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.ENGINE_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.ENGINE_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.ENGINE_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.ENGINE_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        with patch("engine.ecs.get_task_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.run_task.side_effect = CloudTaskError("No tasks started: ['RESOURCE:CPU']")
            mock_get_runner.return_value = mock_runner

            with pytest.raises(CloudTaskError):
                _start_ecs_task(range_id=42, user_id=7, command="provision")

    def test_propagates_get_task_runner_error(self, settings):
        """Function propagates errors from get_task_runner()."""
        from engine.ecs import _start_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.ENGINE_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.ENGINE_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.ENGINE_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.ENGINE_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        with patch("engine.ecs.get_task_runner") as mock_get_runner:
            mock_get_runner.side_effect = RuntimeError("Provider not configured")

            with pytest.raises(RuntimeError, match="Provider not configured"):
                _start_ecs_task(range_id=42, user_id=7, command="provision")


class TestStartEcsTaskLogging:
    """Logging tests for ECS task start."""

    def test_logs_warning_when_config_incomplete(self, settings, caplog):
        """Function logs WARNING when ECS configuration is incomplete."""
        from engine.ecs import _start_ecs_task

        settings.AWS_REGION = "us-east-2"
        if hasattr(settings, "ENGINE_ECS_CLUSTER_ARN"):
            delattr(settings, "ENGINE_ECS_CLUSTER_ARN")

        with caplog.at_level(logging.WARNING, logger="engine.ecs"):
            _start_ecs_task(range_id=42, user_id=7, command="provision")

        log_text = caplog.text.lower()
        assert "warning" in log_text or "incomplete" in log_text or "skipping" in log_text

    def test_logs_error_when_subnet_ids_invalid(self, settings, caplog):
        """Function logs ERROR when subnet IDs are invalid."""
        from engine.ecs import _start_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.ENGINE_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.ENGINE_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.ENGINE_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.ENGINE_PRIVATE_SUBNET_IDS = "   ,   "

        with caplog.at_level(logging.ERROR, logger="engine.ecs"):
            _start_ecs_task(range_id=42, user_id=7, command="provision")

        assert "error" in caplog.text.lower() or "empty" in caplog.text.lower() or "invalid" in caplog.text.lower()

    def test_logs_info_on_success(self, settings, caplog):
        """Function logs INFO when task starts successfully."""
        from engine.ecs import _start_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.ENGINE_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.ENGINE_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.ENGINE_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.ENGINE_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        with (
            patch("engine.ecs.get_task_runner") as mock_get_runner,
            caplog.at_level(logging.INFO, logger="engine.ecs"),
        ):
            mock_runner = MagicMock()
            mock_runner.run_task.return_value = "arn:aws:ecs:us-east-2:123456789:task/test/abc123"
            mock_get_runner.return_value = mock_runner

            _start_ecs_task(range_id=42, user_id=7, command="provision")

        assert "42" in caplog.text or "range_id" in caplog.text.lower()

    def test_logs_error_when_run_task_fails(self, settings, caplog):
        """Function logs ERROR when TaskRunner.run_task fails."""
        from engine.ecs import _start_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.ENGINE_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.ENGINE_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.ENGINE_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.ENGINE_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        with (
            patch("engine.ecs.get_task_runner") as mock_get_runner,
            caplog.at_level(logging.ERROR, logger="engine.ecs"),
            pytest.raises(CloudTaskError),
        ):
            mock_runner = MagicMock()
            mock_runner.run_task.side_effect = CloudTaskError("Cluster not found")
            mock_get_runner.return_value = mock_runner

            _start_ecs_task(range_id=42, user_id=7, command="provision")

        assert "error" in caplog.text.lower() or "failed" in caplog.text.lower()

    def test_logs_error_when_no_tasks_returned(self, settings, caplog):
        """Function logs ERROR when adapter reports no tasks started (CloudTaskError)."""
        from engine.ecs import _start_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.ENGINE_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.ENGINE_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.ENGINE_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.ENGINE_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        with (
            patch("engine.ecs.get_task_runner") as mock_get_runner,
            caplog.at_level(logging.ERROR, logger="engine.ecs"),
            pytest.raises(CloudTaskError),
        ):
            mock_runner = MagicMock()
            mock_runner.run_task.side_effect = CloudTaskError("No tasks started: ['RESOURCE:CPU']")
            mock_get_runner.return_value = mock_runner

            _start_ecs_task(range_id=42, user_id=7, command="provision")

        assert "error" in caplog.text.lower() or "failed" in caplog.text.lower()
