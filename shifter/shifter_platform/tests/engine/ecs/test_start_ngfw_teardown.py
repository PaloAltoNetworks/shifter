"""Tests for start_ngfw_teardown() wrapper function.

start_ngfw_teardown() is a thin wrapper that delegates to _start_ngfw_ecs_task().
Validation, config, error, and logging tests live in test_start_ngfw_ecs_task.py.
"""

from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from shared.cloud.exceptions import CloudTaskError

TEST_REQUEST_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
TEST_REQUEST_ID_2 = UUID("660e8400-e29b-41d4-a716-446655440001")


class TestStartNgfwTeardown:
    """Tests for start_ngfw_teardown() delegation to _start_ngfw_ecs_task."""

    def test_calls_start_ngfw_ecs_task_with_deprovision_command(self, settings):
        """Function calls _start_ngfw_ecs_task with deprovision command."""
        from engine.ecs import start_ngfw_teardown

        with patch("engine.ecs._start_ngfw_ecs_task") as mock_start:
            mock_start.return_value = "arn:aws:ecs:task/123"

            start_ngfw_teardown(request_id=TEST_REQUEST_ID)

            mock_start.assert_called_once()
            call_args = mock_start.call_args
            assert call_args[0][0] == TEST_REQUEST_ID
            command = call_args[0][1]
            assert command[0] == "ngfw"
            assert command[1] == "deprovision"
            assert "--request-id" in command

    def test_command_includes_request_id_as_string(self, settings):
        """Function passes request_id as string in command arguments."""
        from engine.ecs import start_ngfw_teardown

        with patch("engine.ecs._start_ngfw_ecs_task") as mock_start:
            mock_start.return_value = "arn:aws:ecs:task/123"

            start_ngfw_teardown(request_id=TEST_REQUEST_ID_2)

            call_args = mock_start.call_args
            command = call_args[0][1]
            assert str(TEST_REQUEST_ID_2) in command
            expected = [
                "ngfw",
                "deprovision",
                "--request-id",
                str(TEST_REQUEST_ID_2),
            ]
            assert command == expected

    def test_returns_task_arn_on_success(self, settings):
        """Function returns ECS task ARN when teardown starts."""
        from engine.ecs import start_ngfw_teardown

        settings.LOCAL_PROVISIONER = None  # Ensure ECS path is used
        settings.AWS_REGION = "us-east-2"
        settings.ENGINE_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.ENGINE_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.ENGINE_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.ENGINE_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        task_arn = "arn:aws:ecs:us-east-2:123456789:task/test/abc123"

        with patch("engine.ecs.get_task_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.run_task.return_value = task_arn
            mock_get_runner.return_value = mock_runner

            result = start_ngfw_teardown(request_id=TEST_REQUEST_ID)

            assert result == task_arn

    def test_uses_deprovision_not_provision(self, settings):
        """Function uses 'deprovision' command, not 'provision'."""
        from engine.ecs import start_ngfw_teardown

        with patch("engine.ecs._start_ngfw_ecs_task") as mock_start:
            mock_start.return_value = "arn:aws:ecs:task/123"

            start_ngfw_teardown(request_id=TEST_REQUEST_ID)

            call_args = mock_start.call_args
            command = call_args[0][1]
            assert "deprovision" in command
            assert command[1] == "deprovision"

    def test_returns_none_when_ecs_not_configured(self, settings):
        """Returns None when ECS settings are incomplete."""
        from engine.ecs import start_ngfw_teardown

        settings.LOCAL_PROVISIONER = None
        settings.ENGINE_ECS_CLUSTER_ARN = ""
        settings.ENGINE_TASK_DEFINITION_ARN = ""
        settings.ENGINE_ECS_SECURITY_GROUP_ID = ""
        settings.ENGINE_PRIVATE_SUBNET_IDS = ""

        result = start_ngfw_teardown(request_id=TEST_REQUEST_ID)
        assert result is None

    def test_raises_type_error_for_none_request_id(self, settings):
        """Raises TypeError when request_id is None."""
        from engine.ecs import start_ngfw_teardown

        with pytest.raises(TypeError):
            start_ngfw_teardown(request_id=None)

    def test_raises_cloud_task_error_on_task_failure(self, settings):
        """Raises CloudTaskError when the ECS task runner fails."""
        from engine.ecs import start_ngfw_teardown

        settings.LOCAL_PROVISIONER = None
        settings.ENGINE_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123:cluster/test"
        settings.ENGINE_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123:task-definition/test:1"
        settings.ENGINE_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.ENGINE_PRIVATE_SUBNET_IDS = "subnet-1"

        with patch("engine.ecs.get_task_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.run_task.side_effect = CloudTaskError("Task launch failed")
            mock_get_runner.return_value = mock_runner

            with pytest.raises(CloudTaskError):
                start_ngfw_teardown(request_id=TEST_REQUEST_ID)
