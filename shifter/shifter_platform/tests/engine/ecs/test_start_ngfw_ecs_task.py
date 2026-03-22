"""Tests for _start_ngfw_ecs_task() function."""

import logging
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from shared.cloud.exceptions import CloudTaskError

TEST_REQUEST_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
TEST_REQUEST_ID_2 = UUID("660e8400-e29b-41d4-a716-446655440001")


class TestStartNgfwEcsTask:
    """Tests for _start_ngfw_ecs_task() internal function.

    Contract:
    - Inputs: request_id (UUID), command (list[str])
    - Outputs: ECS task ARN (str) if successful, None if ECS not configured
    - Side effects: Calls TaskRunner.run_task via get_task_runner()
    - Errors: TypeError if request_id not UUID, CloudTaskError if ECS fails
    - Logging: WARNING when config incomplete, ERROR on failures
    """

    # -------------------------------------------------------------------------
    # Happy path - function succeeds
    # -------------------------------------------------------------------------

    def test_returns_task_arn_on_success(self, settings):
        """Function returns ECS task ARN when task starts successfully."""
        from engine.ecs import _start_ngfw_ecs_task

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

            result = _start_ngfw_ecs_task(
                request_id=TEST_REQUEST_ID,
                command=["ngfw", "provision", "--request-id", str(TEST_REQUEST_ID)],
            )

            assert result == task_arn

    def test_passes_command_list_to_runner(self, settings):
        """Function passes command list to TaskRunner.run_task."""
        from engine.ecs import _start_ngfw_ecs_task

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

            command = ["ngfw", "deprovision", "--request-id", str(TEST_REQUEST_ID_2)]
            _start_ngfw_ecs_task(request_id=TEST_REQUEST_ID_2, command=command)

            call_kwargs = mock_runner.run_task.call_args[1]
            assert call_kwargs["command"] == command
            assert call_kwargs["container_name"] == "pulumi-provisioner"

    # -------------------------------------------------------------------------
    # Configuration - ECS not configured
    # -------------------------------------------------------------------------

    def test_returns_none_when_cluster_arn_missing(self, settings):
        """Function returns None when ENGINE_ECS_CLUSTER_ARN is not set."""
        from engine.ecs import _start_ngfw_ecs_task

        settings.LOCAL_PROVISIONER = None  # Ensure ECS path is used
        settings.AWS_REGION = "us-east-2"
        if hasattr(settings, "ENGINE_ECS_CLUSTER_ARN"):
            delattr(settings, "ENGINE_ECS_CLUSTER_ARN")
        settings.ENGINE_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.ENGINE_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.ENGINE_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        result = _start_ngfw_ecs_task(
            request_id=TEST_REQUEST_ID,
            command=["ngfw", "provision", "--request-id", str(TEST_REQUEST_ID)],
        )

        assert result is None

    def test_returns_none_when_subnet_ids_whitespace(self, settings):
        """Function returns None when subnet IDs is only whitespace."""
        from engine.ecs import _start_ngfw_ecs_task

        settings.LOCAL_PROVISIONER = None  # Ensure ECS path is used
        settings.AWS_REGION = "us-east-2"
        settings.ENGINE_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.ENGINE_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.ENGINE_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.ENGINE_PRIVATE_SUBNET_IDS = "   ,   ,   "

        result = _start_ngfw_ecs_task(
            request_id=TEST_REQUEST_ID,
            command=["ngfw", "provision", "--request-id", str(TEST_REQUEST_ID)],
        )

        assert result is None

    # -------------------------------------------------------------------------
    # Input validation - request_id
    # -------------------------------------------------------------------------

    def test_validates_request_id_type(self, settings):
        """Function raises TypeError for invalid request_id types."""
        from engine.ecs import _start_ngfw_ecs_task

        settings.LOCAL_PROVISIONER = None
        settings.AWS_REGION = "us-east-2"
        settings.ENGINE_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.ENGINE_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.ENGINE_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.ENGINE_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        invalid_ids = [None, str(TEST_REQUEST_ID), 42]
        for invalid_id in invalid_ids:
            with pytest.raises(TypeError):
                _start_ngfw_ecs_task(request_id=invalid_id, command=["ngfw", "provision"])

    # -------------------------------------------------------------------------
    # Input validation - command
    # -------------------------------------------------------------------------

    def test_validates_command_parameter(self, settings):
        """Function validates command parameter type and content."""
        from engine.ecs import _start_ngfw_ecs_task

        settings.LOCAL_PROVISIONER = None
        settings.AWS_REGION = "us-east-2"
        settings.ENGINE_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.ENGINE_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.ENGINE_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.ENGINE_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        # TypeError for None and string
        for invalid_cmd in [None, "ngfw provision"]:
            with pytest.raises(TypeError):
                _start_ngfw_ecs_task(request_id=TEST_REQUEST_ID, command=invalid_cmd)

        # ValueError for empty list
        with pytest.raises(ValueError):
            _start_ngfw_ecs_task(request_id=TEST_REQUEST_ID, command=[])

    # -------------------------------------------------------------------------
    # Error handling
    # -------------------------------------------------------------------------

    def test_raises_cloud_task_error_when_run_task_fails(self, settings):
        """Function raises CloudTaskError when TaskRunner.run_task fails."""
        from engine.ecs import _start_ngfw_ecs_task

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
                _start_ngfw_ecs_task(
                    request_id=TEST_REQUEST_ID,
                    command=["ngfw", "provision"],
                )

    def test_raises_cloud_task_error_when_no_tasks_returned(self, settings):
        """Function raises CloudTaskError when adapter reports no tasks started."""
        from engine.ecs import _start_ngfw_ecs_task

        settings.LOCAL_PROVISIONER = None  # Ensure ECS path is used
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
                _start_ngfw_ecs_task(
                    request_id=TEST_REQUEST_ID,
                    command=["ngfw", "provision"],
                )

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------

    def test_logs_warning_when_config_incomplete(self, settings, caplog):
        """Function logs WARNING when ECS configuration is incomplete."""
        from engine.ecs import _start_ngfw_ecs_task

        settings.LOCAL_PROVISIONER = None  # Ensure ECS path is used
        settings.AWS_REGION = "us-east-2"
        if hasattr(settings, "ENGINE_ECS_CLUSTER_ARN"):
            delattr(settings, "ENGINE_ECS_CLUSTER_ARN")

        with caplog.at_level(logging.WARNING, logger="engine.ecs"):
            _start_ngfw_ecs_task(
                request_id=TEST_REQUEST_ID,
                command=["ngfw", "provision"],
            )

        log_text = caplog.text.lower()
        assert "incomplete" in log_text or "skipping" in log_text

    def test_logs_info_on_success(self, settings, caplog):
        """Function logs INFO when task starts successfully."""
        from engine.ecs import _start_ngfw_ecs_task

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

            _start_ngfw_ecs_task(
                request_id=TEST_REQUEST_ID,
                command=["ngfw", "provision"],
            )

        assert str(TEST_REQUEST_ID) in caplog.text or "request_id" in caplog.text

    def test_logs_error_when_run_task_fails(self, settings, caplog):
        """Function logs ERROR when TaskRunner.run_task fails."""
        from engine.ecs import _start_ngfw_ecs_task

        settings.LOCAL_PROVISIONER = None  # Ensure ECS path is used
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

            _start_ngfw_ecs_task(
                request_id=TEST_REQUEST_ID,
                command=["ngfw", "provision"],
            )

        assert "error" in caplog.text.lower() or "failed" in caplog.text.lower()
