"""Tests for start_teardown() function."""

import logging
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError


class TestStartTeardown:
    """Tests for start_teardown() public function.

    Contract:
    - Inputs: range_id (int), user_id (int)
    - Outputs: ECS task ARN (str) if successful, None if ECS not configured
    - Side effects: Calls _start_ecs_task with "destroy" command
    - Errors: Propagates errors from _start_ecs_task
    - Logging: Delegates to _start_ecs_task
    """

    # -------------------------------------------------------------------------
    # Happy path - function succeeds
    # -------------------------------------------------------------------------

    def test_returns_task_arn_on_success(self, settings):
        """Function returns ECS task ARN when teardown starts."""
        from engine.ecs import start_teardown

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.PULUMI_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.PULUMI_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.PULUMI_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        mock_response = {"tasks": [{"taskArn": "arn:aws:ecs:us-east-2:123456789:task/test/abc123"}]}

        with patch("engine.ecs._get_ecs_client") as mock_get_client:
            mock_ecs = MagicMock()
            mock_ecs.run_task.return_value = mock_response
            mock_get_client.return_value = mock_ecs

            result = start_teardown(range_id=42, user_id=7)

            assert result == "arn:aws:ecs:us-east-2:123456789:task/test/abc123"

    def test_calls_start_ecs_task_with_destroy_command(self, settings):
        """Function calls _start_ecs_task with range_id, user_id, and 'destroy' command."""
        from engine.ecs import start_teardown

        with patch("engine.ecs._start_ecs_task") as mock_start:
            mock_start.return_value = "arn:aws:ecs:task/123"

            start_teardown(range_id=42, user_id=7)

            mock_start.assert_called_once_with(42, 7, "destroy")

    # -------------------------------------------------------------------------
    # Configuration - ECS not configured
    # -------------------------------------------------------------------------

    def test_returns_none_when_ecs_not_configured(self, settings):
        """Function returns None when ECS is not configured."""
        from engine.ecs import start_teardown

        settings.AWS_REGION = "us-east-2"
        if hasattr(settings, "PULUMI_ECS_CLUSTER_ARN"):
            delattr(settings, "PULUMI_ECS_CLUSTER_ARN")

        result = start_teardown(range_id=42, user_id=7)

        assert result is None

    # -------------------------------------------------------------------------
    # Input validation - inherited from _start_ecs_task
    # -------------------------------------------------------------------------

    def test_raises_when_range_id_is_none(self, settings):
        """Function raises error when range_id is None."""
        from engine.ecs import start_teardown

        with pytest.raises((TypeError, ValueError)):
            start_teardown(range_id=None, user_id=7)

    def test_raises_when_range_id_is_negative(self, settings):
        """Function raises error when range_id is negative."""
        from engine.ecs import start_teardown

        with pytest.raises((TypeError, ValueError)):
            start_teardown(range_id=-1, user_id=7)

    def test_raises_when_range_id_is_string(self, settings):
        """Function raises error when range_id is a string."""
        from engine.ecs import start_teardown

        with pytest.raises((TypeError, ValueError)):
            start_teardown(range_id="42", user_id=7)

    def test_raises_when_user_id_is_none(self, settings):
        """Function raises error when user_id is None."""
        from engine.ecs import start_teardown

        with pytest.raises((TypeError, ValueError)):
            start_teardown(range_id=42, user_id=None)

    def test_raises_when_user_id_is_negative(self, settings):
        """Function raises error when user_id is negative."""
        from engine.ecs import start_teardown

        with pytest.raises((TypeError, ValueError)):
            start_teardown(range_id=42, user_id=-1)

    def test_raises_when_user_id_is_string(self, settings):
        """Function raises error when user_id is a string."""
        from engine.ecs import start_teardown

        with pytest.raises((TypeError, ValueError)):
            start_teardown(range_id=42, user_id="7")

    # -------------------------------------------------------------------------
    # Error handling
    # -------------------------------------------------------------------------

    def test_propagates_client_error(self, settings):
        """Function propagates ClientError from _start_ecs_task."""
        from engine.ecs import start_teardown

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.PULUMI_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.PULUMI_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.PULUMI_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        with patch("engine.ecs._get_ecs_client") as mock_get_client:
            mock_ecs = MagicMock()
            mock_ecs.run_task.side_effect = ClientError(
                {"Error": {"Code": "ClusterNotFound", "Message": "Cluster not found"}},
                "RunTask",
            )
            mock_get_client.return_value = mock_ecs

            with pytest.raises(ClientError):
                start_teardown(range_id=42, user_id=7)

    # -------------------------------------------------------------------------
    # Logging - delegates to _start_ecs_task
    # -------------------------------------------------------------------------

    def test_logs_info_on_success(self, settings, caplog):
        """Function logs INFO when teardown starts."""
        from engine.ecs import start_teardown

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.PULUMI_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.PULUMI_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.PULUMI_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        mock_response = {"tasks": [{"taskArn": "arn:aws:ecs:us-east-2:123456789:task/test/abc123"}]}

        with (
            patch("engine.ecs._get_ecs_client") as mock_get_client,
            caplog.at_level(logging.INFO, logger="engine.ecs"),
        ):
            mock_ecs = MagicMock()
            mock_ecs.run_task.return_value = mock_response
            mock_get_client.return_value = mock_ecs

            start_teardown(range_id=42, user_id=7)

        assert "42" in caplog.text or "destroy" in caplog.text.lower()
