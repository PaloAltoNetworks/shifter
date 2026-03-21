"""Tests for start_teardown() wrapper function.

start_teardown() delegates to _start_ecs_task(), which handles
validation, config checks, and error wrapping.
"""

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from shared.cloud.exceptions import CloudTaskError


class TestStartTeardown:
    """Tests for start_teardown() — delegation, validation, config, errors."""

    def test_calls_start_ecs_task_with_destroy_command(self, settings):
        """Function calls _start_ecs_task with range_id, user_id, and 'destroy' command."""
        from engine.ecs import start_teardown

        with patch("engine.ecs._start_ecs_task") as mock_start:
            mock_start.return_value = "arn:aws:ecs:task/123"

            start_teardown(range_id=42, user_id=7)

            mock_start.assert_called_once_with(42, 7, "destroy")

    def test_returns_task_arn_on_success(self, settings):
        """Function returns ECS task ARN when teardown starts."""
        from engine.ecs import start_teardown

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.PULUMI_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.PULUMI_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.PULUMI_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        with patch("engine.ecs.get_task_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.run_task.return_value = "arn:aws:ecs:us-east-2:123456789:task/test/abc123"
            mock_get_runner.return_value = mock_runner

            result = start_teardown(range_id=42, user_id=7)

            assert result == "arn:aws:ecs:us-east-2:123456789:task/test/abc123"

    def test_returns_none_when_ecs_not_configured(self, settings):
        """Returns None when ECS settings are incomplete."""
        from engine.ecs import start_teardown

        settings.PULUMI_ECS_CLUSTER_ARN = ""
        settings.PULUMI_TASK_DEFINITION_ARN = ""
        settings.PULUMI_ECS_SECURITY_GROUP_ID = ""
        settings.PULUMI_PRIVATE_SUBNET_IDS = ""

        result = start_teardown(range_id=42, user_id=7)
        assert result is None

    @pytest.mark.parametrize(
        "range_id,user_id,exc_type",
        [
            pytest.param(None, 7, TypeError, id="none-range_id"),
            pytest.param(-1, 7, ValueError, id="negative-range_id"),
            pytest.param(42, None, TypeError, id="none-user_id"),
            pytest.param(42, -1, ValueError, id="negative-user_id"),
        ],
    )
    def test_raises_on_invalid_input(self, settings, range_id, user_id, exc_type):
        """Raises TypeError/ValueError for invalid range_id or user_id."""
        from engine.ecs import start_teardown

        with pytest.raises(exc_type):
            start_teardown(range_id=range_id, user_id=user_id)

    def test_raises_client_error_on_task_failure(self, settings):
        """Raises ClientError when the ECS task runner fails."""
        from engine.ecs import start_teardown

        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123:cluster/test"
        settings.PULUMI_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123:task-definition/test:1"
        settings.PULUMI_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.PULUMI_PRIVATE_SUBNET_IDS = "subnet-1"

        with patch("engine.ecs.get_task_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.run_task.side_effect = CloudTaskError("Task launch failed")
            mock_get_runner.return_value = mock_runner

            with pytest.raises(ClientError):
                start_teardown(range_id=42, user_id=7)
