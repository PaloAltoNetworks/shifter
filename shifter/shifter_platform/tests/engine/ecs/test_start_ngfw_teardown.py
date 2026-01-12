"""Tests for start_ngfw_teardown() function."""

import logging
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from botocore.exceptions import ClientError

TEST_REQUEST_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
TEST_REQUEST_ID_2 = UUID("660e8400-e29b-41d4-a716-446655440001")


class TestStartNgfwTeardown:
    """Tests for start_ngfw_teardown() public function.

    Contract:
    - Inputs: request_id (UUID)
    - Outputs: ECS task ARN (str) if successful, None if ECS not configured
    - Side effects: Calls _start_ngfw_ecs_task with deprovision command
    - Errors: Propagates TypeError from validation, ClientError from ECS
    - Logging: Delegates to _start_ngfw_ecs_task
    """

    # -------------------------------------------------------------------------
    # Happy path - function succeeds
    # -------------------------------------------------------------------------

    def test_returns_task_arn_on_success(self, settings):
        """Function returns ECS task ARN when teardown starts."""
        from engine.ecs import start_ngfw_teardown

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.PULUMI_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.PULUMI_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.PULUMI_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        task_arn = "arn:aws:ecs:us-east-2:123456789:task/test/abc123"
        mock_response = {"tasks": [{"taskArn": task_arn}]}

        with patch("engine.ecs._get_ecs_client") as mock_get_client:
            mock_ecs = MagicMock()
            mock_ecs.run_task.return_value = mock_response
            mock_get_client.return_value = mock_ecs

            result = start_ngfw_teardown(request_id=TEST_REQUEST_ID)

            assert result == task_arn

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

    # -------------------------------------------------------------------------
    # Configuration - ECS not configured
    # -------------------------------------------------------------------------

    def test_returns_none_when_ecs_not_configured(self, settings):
        """Function returns None when ECS is not configured."""
        from engine.ecs import start_ngfw_teardown

        settings.AWS_REGION = "us-east-2"
        if hasattr(settings, "PULUMI_ECS_CLUSTER_ARN"):
            delattr(settings, "PULUMI_ECS_CLUSTER_ARN")

        result = start_ngfw_teardown(request_id=TEST_REQUEST_ID)

        assert result is None

    def test_returns_none_when_task_definition_missing(self, settings):
        """Function returns None when task definition is missing."""
        from engine.ecs import start_ngfw_teardown

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        if hasattr(settings, "PULUMI_TASK_DEFINITION_ARN"):
            delattr(settings, "PULUMI_TASK_DEFINITION_ARN")

        result = start_ngfw_teardown(request_id=TEST_REQUEST_ID)

        assert result is None

    def test_returns_none_when_subnet_ids_empty(self, settings):
        """Function returns None when subnet IDs are empty."""
        from engine.ecs import start_ngfw_teardown

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.PULUMI_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.PULUMI_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.PULUMI_PRIVATE_SUBNET_IDS = ""

        result = start_ngfw_teardown(request_id=TEST_REQUEST_ID)

        assert result is None

    # -------------------------------------------------------------------------
    # Input validation
    # -------------------------------------------------------------------------

    def test_raises_type_error_when_request_id_is_none(self, settings):
        """Function raises TypeError when request_id is None."""
        from engine.ecs import start_ngfw_teardown

        with pytest.raises(TypeError):
            start_ngfw_teardown(request_id=None)

    def test_raises_type_error_when_request_id_is_string(self, settings):
        """Function raises TypeError when request_id is a string."""
        from engine.ecs import start_ngfw_teardown

        with pytest.raises(TypeError):
            start_ngfw_teardown(request_id=str(TEST_REQUEST_ID))

    def test_raises_type_error_when_request_id_is_int(self, settings):
        """Function raises TypeError when request_id is an integer."""
        from engine.ecs import start_ngfw_teardown

        with pytest.raises(TypeError):
            start_ngfw_teardown(request_id=42)

    # -------------------------------------------------------------------------
    # Error handling - propagates errors
    # -------------------------------------------------------------------------

    def test_propagates_client_error_from_ecs(self, settings):
        """Function propagates ClientError from _start_ngfw_ecs_task."""
        from engine.ecs import start_ngfw_teardown

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.PULUMI_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.PULUMI_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.PULUMI_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        with patch("engine.ecs._get_ecs_client") as mock_get_client:
            mock_ecs = MagicMock()
            mock_ecs.run_task.side_effect = ClientError(
                {"Error": {"Code": "ClusterNotFound", "Message": "Not found"}},
                "RunTask",
            )
            mock_get_client.return_value = mock_ecs

            with pytest.raises(ClientError):
                start_ngfw_teardown(request_id=TEST_REQUEST_ID)

    def test_propagates_type_error_from_validation(self, settings):
        """Function propagates TypeError for invalid request_id."""
        from engine.ecs import start_ngfw_teardown

        with pytest.raises(TypeError):
            start_ngfw_teardown(request_id=None)

    # -------------------------------------------------------------------------
    # Logging - delegates to _start_ngfw_ecs_task
    # -------------------------------------------------------------------------

    def test_logs_info_on_success(self, settings, caplog):
        """Function logs INFO when teardown starts."""
        from engine.ecs import start_ngfw_teardown

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.PULUMI_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.PULUMI_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.PULUMI_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        task_arn = "arn:aws:ecs:us-east-2:123456789:task/test/abc123"
        mock_response = {"tasks": [{"taskArn": task_arn}]}

        with (
            patch("engine.ecs._get_ecs_client") as mock_get_client,
            caplog.at_level(logging.INFO, logger="engine.ecs"),
        ):
            mock_ecs = MagicMock()
            mock_ecs.run_task.return_value = mock_response
            mock_get_client.return_value = mock_ecs

            start_ngfw_teardown(request_id=TEST_REQUEST_ID)

        assert str(TEST_REQUEST_ID) in caplog.text or "ngfw" in caplog.text.lower()

    def test_logs_warning_when_config_incomplete(self, settings, caplog):
        """Function logs WARNING when ECS configuration is incomplete."""
        from engine.ecs import start_ngfw_teardown

        settings.AWS_REGION = "us-east-2"
        if hasattr(settings, "PULUMI_ECS_CLUSTER_ARN"):
            delattr(settings, "PULUMI_ECS_CLUSTER_ARN")

        with caplog.at_level(logging.WARNING, logger="engine.ecs"):
            start_ngfw_teardown(request_id=TEST_REQUEST_ID)

        log_text = caplog.text.lower()
        assert "incomplete" in log_text or "skipping" in log_text

    # -------------------------------------------------------------------------
    # Difference from start_ngfw_provisioning
    # -------------------------------------------------------------------------

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
