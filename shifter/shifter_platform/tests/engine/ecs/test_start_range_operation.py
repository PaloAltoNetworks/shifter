"""Tests for start_range_operation() function."""

import logging
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from botocore.exceptions import ClientError

TEST_REQUEST_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
TEST_REQUEST_ID_2 = UUID("660e8400-e29b-41d4-a716-446655440001")


class TestStartRangeOperation:
    """Tests for start_range_operation() function.

    Contract:
    - Inputs: request_id (UUID), operation (str: 'pause' or 'resume')
    - Outputs: ECS task ARN (str) if successful, None if ECS not configured
    - Side effects: Calls ECS run_task API via _start_range_ecs_task
    - Errors: TypeError if request_id not UUID, ValueError if operation invalid
    - Logging: WARNING when config incomplete, ERROR on failures
    """

    # -------------------------------------------------------------------------
    # Happy path - function succeeds
    # -------------------------------------------------------------------------

    def test_returns_task_arn_on_success_for_pause(self, settings):
        """Function returns ECS task ARN when pause operation starts successfully."""
        from engine.ecs import start_range_operation

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

            result = start_range_operation(request_id=TEST_REQUEST_ID, operation="pause")

            assert result == task_arn

    def test_returns_task_arn_on_success_for_resume(self, settings):
        """Function returns ECS task ARN when resume operation starts successfully."""
        from engine.ecs import start_range_operation

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.PULUMI_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.PULUMI_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.PULUMI_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        task_arn = "arn:aws:ecs:us-east-2:123456789:task/test/def456"
        mock_response = {"tasks": [{"taskArn": task_arn}]}

        with patch("engine.ecs._get_ecs_client") as mock_get_client:
            mock_ecs = MagicMock()
            mock_ecs.run_task.return_value = mock_response
            mock_get_client.return_value = mock_ecs

            result = start_range_operation(request_id=TEST_REQUEST_ID, operation="resume")

            assert result == task_arn

    def test_passes_correct_command_for_pause(self, settings):
        """Function passes 'pause' command to _start_range_ecs_task."""
        from engine.ecs import start_range_operation

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

            start_range_operation(request_id=TEST_REQUEST_ID, operation="pause")

            # Verify the command includes 'pause'
            call_kwargs = mock_ecs.run_task.call_args[1]
            overrides = call_kwargs["overrides"]["containerOverrides"][0]
            command = overrides["command"]
            assert "pause" in command

    def test_passes_correct_command_for_resume(self, settings):
        """Function passes 'resume' command to _start_range_ecs_task."""
        from engine.ecs import start_range_operation

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

            start_range_operation(request_id=TEST_REQUEST_ID, operation="resume")

            # Verify the command includes 'resume'
            call_kwargs = mock_ecs.run_task.call_args[1]
            overrides = call_kwargs["overrides"]["containerOverrides"][0]
            command = overrides["command"]
            assert "resume" in command

    # -------------------------------------------------------------------------
    # Input validation - operation
    # -------------------------------------------------------------------------

    def test_raises_value_error_for_invalid_operation(self, settings):
        """Function raises ValueError when operation is not 'pause' or 'resume'."""
        from engine.ecs import start_range_operation

        with pytest.raises(ValueError, match="Invalid operation"):
            start_range_operation(request_id=TEST_REQUEST_ID, operation="invalid")

    def test_raises_value_error_for_provision_operation(self, settings):
        """Function raises ValueError when operation is 'provision' (use different function)."""
        from engine.ecs import start_range_operation

        with pytest.raises(ValueError, match="Invalid operation"):
            start_range_operation(request_id=TEST_REQUEST_ID, operation="provision")

    def test_raises_value_error_for_destroy_operation(self, settings):
        """Function raises ValueError when operation is 'destroy' (use different function)."""
        from engine.ecs import start_range_operation

        with pytest.raises(ValueError, match="Invalid operation"):
            start_range_operation(request_id=TEST_REQUEST_ID, operation="destroy")

    # -------------------------------------------------------------------------
    # Input validation - request_id
    # -------------------------------------------------------------------------

    def test_raises_when_request_id_is_none(self, settings):
        """Function raises TypeError when request_id is None."""
        from engine.ecs import start_range_operation

        with pytest.raises(TypeError):
            start_range_operation(request_id=None, operation="pause")

    def test_raises_when_request_id_is_string(self, settings):
        """Function raises TypeError when request_id is a string (not UUID)."""
        from engine.ecs import start_range_operation

        with pytest.raises(TypeError):
            start_range_operation(request_id=str(TEST_REQUEST_ID), operation="pause")

    def test_raises_when_request_id_is_int(self, settings):
        """Function raises TypeError when request_id is an integer."""
        from engine.ecs import start_range_operation

        with pytest.raises(TypeError):
            start_range_operation(request_id=42, operation="pause")

    # -------------------------------------------------------------------------
    # Configuration - ECS not configured
    # -------------------------------------------------------------------------

    def test_returns_none_when_cluster_arn_missing(self, settings):
        """Function returns None when PULUMI_ECS_CLUSTER_ARN is not set."""
        from engine.ecs import start_range_operation

        settings.AWS_REGION = "us-east-2"
        if hasattr(settings, "PULUMI_ECS_CLUSTER_ARN"):
            delattr(settings, "PULUMI_ECS_CLUSTER_ARN")
        settings.PULUMI_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.PULUMI_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.PULUMI_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        result = start_range_operation(request_id=TEST_REQUEST_ID, operation="pause")

        assert result is None

    def test_returns_none_when_task_definition_missing(self, settings):
        """Function returns None when PULUMI_TASK_DEFINITION_ARN is not set."""
        from engine.ecs import start_range_operation

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        if hasattr(settings, "PULUMI_TASK_DEFINITION_ARN"):
            delattr(settings, "PULUMI_TASK_DEFINITION_ARN")
        settings.PULUMI_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.PULUMI_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        result = start_range_operation(request_id=TEST_REQUEST_ID, operation="resume")

        assert result is None

    # -------------------------------------------------------------------------
    # Error handling
    # -------------------------------------------------------------------------

    def test_raises_client_error_when_run_task_fails(self, settings):
        """Function raises ClientError when ECS run_task fails."""
        from engine.ecs import start_range_operation

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
                start_range_operation(request_id=TEST_REQUEST_ID, operation="pause")

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------

    def test_logs_warning_when_config_incomplete(self, settings, caplog):
        """Function logs WARNING when ECS configuration is incomplete."""
        from engine.ecs import start_range_operation

        settings.AWS_REGION = "us-east-2"
        if hasattr(settings, "PULUMI_ECS_CLUSTER_ARN"):
            delattr(settings, "PULUMI_ECS_CLUSTER_ARN")

        with caplog.at_level(logging.WARNING, logger="engine.ecs"):
            start_range_operation(request_id=TEST_REQUEST_ID, operation="pause")

        log_text = caplog.text.lower()
        assert "incomplete" in log_text or "skipping" in log_text

    def test_logs_info_on_success(self, settings, caplog):
        """Function logs INFO when task starts successfully."""
        from engine.ecs import start_range_operation

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

            start_range_operation(request_id=TEST_REQUEST_ID, operation="pause")

        assert str(TEST_REQUEST_ID) in caplog.text or "request_id" in caplog.text
