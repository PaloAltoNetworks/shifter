"""Tests for start_range_operation() function."""

import logging
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from shared.cloud.exceptions import CloudTaskError

TEST_REQUEST_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
TEST_REQUEST_ID_2 = UUID("660e8400-e29b-41d4-a716-446655440001")


class TestStartRangeOperation:
    """Tests for start_range_operation() function.

    Contract:
    - Inputs: request_id (UUID), operation (str: 'pause' or 'resume')
    - Outputs: ECS task ARN (str) if successful, None if ECS not configured
    - Side effects: Calls TaskRunner.run_task via _start_range_ecs_task
    - Errors: TypeError if request_id not UUID, ValueError if operation invalid
    - Logging: WARNING when config incomplete, ERROR on failures
    """

    # -------------------------------------------------------------------------
    # Happy path - function succeeds
    # -------------------------------------------------------------------------

    def test_returns_task_arn_on_success_for_pause(self, settings):
        """Function returns ECS task ARN when pause operation starts successfully."""
        from engine.ecs import start_range_operation

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

            result = start_range_operation(request_id=TEST_REQUEST_ID, operation="pause")

            assert result == task_arn

    def test_returns_task_arn_on_success_for_resume(self, settings):
        """Function returns ECS task ARN when resume operation starts successfully."""
        from engine.ecs import start_range_operation

        settings.LOCAL_PROVISIONER = None  # Ensure ECS path is used
        settings.AWS_REGION = "us-east-2"
        settings.ENGINE_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.ENGINE_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.ENGINE_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.ENGINE_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        task_arn = "arn:aws:ecs:us-east-2:123456789:task/test/def456"

        with patch("engine.ecs.get_task_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.run_task.return_value = task_arn
            mock_get_runner.return_value = mock_runner

            result = start_range_operation(request_id=TEST_REQUEST_ID, operation="resume")

            assert result == task_arn

    def test_passes_correct_command_for_pause(self, settings):
        """Function passes 'pause' command to TaskRunner.run_task."""
        from engine.ecs import start_range_operation

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

            start_range_operation(request_id=TEST_REQUEST_ID, operation="pause")

            call_kwargs = mock_runner.run_task.call_args[1]
            assert "pause" in call_kwargs["command"]

    def test_passes_correct_command_for_resume(self, settings):
        """Function passes 'resume' command to TaskRunner.run_task."""
        from engine.ecs import start_range_operation

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

            start_range_operation(request_id=TEST_REQUEST_ID, operation="resume")

            call_kwargs = mock_runner.run_task.call_args[1]
            assert "resume" in call_kwargs["command"]

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
        """Function returns None when ENGINE_ECS_CLUSTER_ARN is not set."""
        from engine.ecs import start_range_operation

        settings.LOCAL_PROVISIONER = None  # Ensure ECS path is used
        settings.AWS_REGION = "us-east-2"
        if hasattr(settings, "ENGINE_ECS_CLUSTER_ARN"):
            delattr(settings, "ENGINE_ECS_CLUSTER_ARN")
        settings.ENGINE_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.ENGINE_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.ENGINE_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        result = start_range_operation(request_id=TEST_REQUEST_ID, operation="pause")

        assert result is None

    def test_returns_none_when_task_definition_missing(self, settings):
        """Function returns None when ENGINE_TASK_DEFINITION_ARN is not set."""
        from engine.ecs import start_range_operation

        settings.LOCAL_PROVISIONER = None  # Ensure ECS path is used
        settings.AWS_REGION = "us-east-2"
        settings.ENGINE_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        if hasattr(settings, "ENGINE_TASK_DEFINITION_ARN"):
            delattr(settings, "ENGINE_TASK_DEFINITION_ARN")
        settings.ENGINE_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.ENGINE_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        result = start_range_operation(request_id=TEST_REQUEST_ID, operation="resume")

        assert result is None

    # -------------------------------------------------------------------------
    # Error handling
    # -------------------------------------------------------------------------

    def test_raises_cloud_task_error_when_run_task_fails(self, settings):
        """Function raises CloudTaskError when TaskRunner.run_task fails."""
        from engine.ecs import start_range_operation

        settings.LOCAL_PROVISIONER = None  # Ensure ECS path is used
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
                start_range_operation(request_id=TEST_REQUEST_ID, operation="pause")

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------

    def test_logs_warning_when_config_incomplete(self, settings, caplog):
        """Function logs WARNING when ECS configuration is incomplete."""
        from engine.ecs import start_range_operation

        settings.LOCAL_PROVISIONER = None  # Ensure ECS path is used
        settings.AWS_REGION = "us-east-2"
        if hasattr(settings, "ENGINE_ECS_CLUSTER_ARN"):
            delattr(settings, "ENGINE_ECS_CLUSTER_ARN")

        with caplog.at_level(logging.WARNING, logger="engine.ecs"):
            start_range_operation(request_id=TEST_REQUEST_ID, operation="pause")

        log_text = caplog.text.lower()
        assert "incomplete" in log_text or "skipping" in log_text

    def test_logs_info_on_success(self, settings, caplog):
        """Function logs INFO when task starts successfully."""
        from engine.ecs import start_range_operation

        settings.LOCAL_PROVISIONER = None  # Ensure ECS path is used
        settings.AWS_REGION = "us-east-2"
        settings.ENGINE_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.ENGINE_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.ENGINE_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.ENGINE_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        task_arn = "arn:aws:ecs:us-east-2:123456789:task/test/abc123"

        with (
            patch("engine.ecs.get_task_runner") as mock_get_runner,
            caplog.at_level(logging.INFO, logger="engine.ecs"),
        ):
            mock_runner = MagicMock()
            mock_runner.run_task.return_value = task_arn
            mock_get_runner.return_value = mock_runner

            start_range_operation(request_id=TEST_REQUEST_ID, operation="pause")

        assert str(TEST_REQUEST_ID) in caplog.text or "request_id" in caplog.text
