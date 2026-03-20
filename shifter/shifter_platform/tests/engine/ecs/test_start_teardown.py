"""Tests for start_teardown() wrapper function.

start_teardown() is a thin wrapper that delegates to _start_ecs_task().
Validation, config, error, and logging tests live in test_start_ecs_task.py.
"""

from unittest.mock import MagicMock, patch


class TestStartTeardown:
    """Tests for start_teardown() delegation to _start_ecs_task."""

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
