"""Tests for _start_ngfw_ecs_task() function."""

import logging
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from botocore.exceptions import ClientError

TEST_REQUEST_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
TEST_REQUEST_ID_2 = UUID("660e8400-e29b-41d4-a716-446655440001")


class TestStartNgfwEcsTask:
    """Tests for _start_ngfw_ecs_task() internal function.

    Contract:
    - Inputs: request_id (UUID), command (list[str])
    - Outputs: ECS task ARN (str) if successful, None if ECS not configured
    - Side effects: Calls ECS run_task API
    - Errors: TypeError if request_id not UUID, ClientError if ECS fails
    - Logging: WARNING when config incomplete, ERROR on failures
    """

    # -------------------------------------------------------------------------
    # Happy path - function succeeds
    # -------------------------------------------------------------------------

    def test_returns_task_arn_on_success(self, settings):
        """Function returns ECS task ARN when task starts successfully."""
        from engine.ecs import _start_ngfw_ecs_task

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

            result = _start_ngfw_ecs_task(
                request_id=TEST_REQUEST_ID,
                command=["ngfw", "provision", "--request-id", str(TEST_REQUEST_ID)],
            )

            assert result == task_arn

    def test_passes_command_list_to_container(self, settings):
        """Function passes command list directly to container overrides."""
        from engine.ecs import _start_ngfw_ecs_task

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

            command = ["ngfw", "deprovision", "--request-id", str(TEST_REQUEST_ID_2)]
            _start_ngfw_ecs_task(request_id=TEST_REQUEST_ID_2, command=command)

            call_kwargs = mock_ecs.run_task.call_args[1]
            overrides = call_kwargs["overrides"]["containerOverrides"][0]
            assert overrides["command"] == command

    # -------------------------------------------------------------------------
    # Configuration - ECS not configured
    # -------------------------------------------------------------------------

    def test_returns_none_when_cluster_arn_missing(self, settings):
        """Function returns None when PULUMI_ECS_CLUSTER_ARN is not set."""
        from engine.ecs import _start_ngfw_ecs_task

        settings.AWS_REGION = "us-east-2"
        if hasattr(settings, "PULUMI_ECS_CLUSTER_ARN"):
            delattr(settings, "PULUMI_ECS_CLUSTER_ARN")
        settings.PULUMI_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.PULUMI_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.PULUMI_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        result = _start_ngfw_ecs_task(
            request_id=TEST_REQUEST_ID,
            command=["ngfw", "provision", "--request-id", str(TEST_REQUEST_ID)],
        )

        assert result is None

    def test_returns_none_when_subnet_ids_whitespace(self, settings):
        """Function returns None when subnet IDs is only whitespace."""
        from engine.ecs import _start_ngfw_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.PULUMI_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.PULUMI_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.PULUMI_PRIVATE_SUBNET_IDS = "   ,   ,   "

        result = _start_ngfw_ecs_task(
            request_id=TEST_REQUEST_ID,
            command=["ngfw", "provision", "--request-id", str(TEST_REQUEST_ID)],
        )

        assert result is None

    # -------------------------------------------------------------------------
    # Input validation - request_id
    # -------------------------------------------------------------------------

    def test_raises_when_request_id_is_none(self, settings):
        """Function raises TypeError when request_id is None."""
        from engine.ecs import _start_ngfw_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.PULUMI_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.PULUMI_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.PULUMI_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        with pytest.raises(TypeError):
            _start_ngfw_ecs_task(request_id=None, command=["ngfw", "provision"])

    def test_raises_when_request_id_is_string(self, settings):
        """Function raises TypeError when request_id is a string (not UUID)."""
        from engine.ecs import _start_ngfw_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.PULUMI_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.PULUMI_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.PULUMI_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        with pytest.raises(TypeError):
            _start_ngfw_ecs_task(
                request_id=str(TEST_REQUEST_ID),
                command=["ngfw", "provision"],
            )

    def test_raises_when_request_id_is_int(self, settings):
        """Function raises TypeError when request_id is an integer."""
        from engine.ecs import _start_ngfw_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.PULUMI_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.PULUMI_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.PULUMI_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        with pytest.raises(TypeError):
            _start_ngfw_ecs_task(request_id=42, command=["ngfw", "provision"])

    # -------------------------------------------------------------------------
    # Input validation - command
    # -------------------------------------------------------------------------

    def test_raises_when_command_is_none(self, settings):
        """Function raises TypeError when command is None."""
        from engine.ecs import _start_ngfw_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.PULUMI_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.PULUMI_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.PULUMI_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        with pytest.raises(TypeError):
            _start_ngfw_ecs_task(request_id=TEST_REQUEST_ID, command=None)

    def test_raises_when_command_is_empty_list(self, settings):
        """Function raises ValueError when command is empty list."""
        from engine.ecs import _start_ngfw_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.PULUMI_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.PULUMI_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.PULUMI_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        with pytest.raises(ValueError):
            _start_ngfw_ecs_task(request_id=TEST_REQUEST_ID, command=[])

    def test_raises_when_command_is_string(self, settings):
        """Function raises TypeError when command is a string instead of list."""
        from engine.ecs import _start_ngfw_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.PULUMI_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.PULUMI_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.PULUMI_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        with pytest.raises(TypeError):
            _start_ngfw_ecs_task(request_id=TEST_REQUEST_ID, command="ngfw provision")

    # -------------------------------------------------------------------------
    # Error handling
    # -------------------------------------------------------------------------

    def test_raises_client_error_when_run_task_fails(self, settings):
        """Function raises ClientError when ECS run_task fails."""
        from engine.ecs import _start_ngfw_ecs_task

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
                _start_ngfw_ecs_task(
                    request_id=TEST_REQUEST_ID,
                    command=["ngfw", "provision"],
                )

    def test_raises_client_error_when_no_tasks_returned(self, settings):
        """Function raises ClientError when ECS returns empty tasks list."""
        from engine.ecs import _start_ngfw_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.PULUMI_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.PULUMI_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.PULUMI_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        mock_response = {
            "tasks": [],
            "failures": [{"reason": "RESOURCE:CPU"}],
        }

        with patch("engine.ecs._get_ecs_client") as mock_get_client:
            mock_ecs = MagicMock()
            mock_ecs.run_task.return_value = mock_response
            mock_get_client.return_value = mock_ecs

            with pytest.raises(ClientError):
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

        settings.AWS_REGION = "us-east-2"
        if hasattr(settings, "PULUMI_ECS_CLUSTER_ARN"):
            delattr(settings, "PULUMI_ECS_CLUSTER_ARN")

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

            _start_ngfw_ecs_task(
                request_id=TEST_REQUEST_ID,
                command=["ngfw", "provision"],
            )

        assert str(TEST_REQUEST_ID) in caplog.text or "request_id" in caplog.text

    def test_logs_error_when_run_task_fails(self, settings, caplog):
        """Function logs ERROR when ECS run_task fails."""
        from engine.ecs import _start_ngfw_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.PULUMI_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.PULUMI_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.PULUMI_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        with (
            patch("engine.ecs._get_ecs_client") as mock_get_client,
            caplog.at_level(logging.ERROR, logger="engine.ecs"),
            pytest.raises(ClientError),
        ):
            mock_ecs = MagicMock()
            mock_ecs.run_task.side_effect = ClientError(
                {"Error": {"Code": "ClusterNotFound", "Message": "Not found"}},
                "RunTask",
            )
            mock_get_client.return_value = mock_ecs

            _start_ngfw_ecs_task(
                request_id=TEST_REQUEST_ID,
                command=["ngfw", "provision"],
            )

        assert "error" in caplog.text.lower() or "failed" in caplog.text.lower()
