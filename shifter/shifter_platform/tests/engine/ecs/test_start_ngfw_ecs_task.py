"""Tests for _start_ngfw_ecs_task() function."""

import logging
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError


class TestStartNgfwEcsTask:
    """Tests for _start_ngfw_ecs_task() internal function.

    Contract:
    - Inputs: ngfw_id (int), command (list[str])
    - Outputs: ECS task ARN (str) if successful, None if ECS not configured
    - Side effects: Calls ECS run_task API
    - Errors: Raises ClientError if ECS task fails to start
    - Logging: WARNING when config incomplete, ERROR on failures, INFO on success
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

        mock_response = {"tasks": [{"taskArn": "arn:aws:ecs:us-east-2:123456789:task/test/abc123"}]}

        with patch("engine.ecs._get_ecs_client") as mock_get_client:
            mock_ecs = MagicMock()
            mock_ecs.run_task.return_value = mock_response
            mock_get_client.return_value = mock_ecs

            result = _start_ngfw_ecs_task(ngfw_id=42, command=["ngfw", "provision", "--user-ngfw-id", "42"])

            assert result == "arn:aws:ecs:us-east-2:123456789:task/test/abc123"

    def test_passes_command_list_to_container(self, settings):
        """Function passes command list directly to container overrides."""
        from engine.ecs import _start_ngfw_ecs_task

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

            command = ["ngfw", "deprovision", "--user-ngfw-id", "99"]
            _start_ngfw_ecs_task(ngfw_id=99, command=command)

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

        result = _start_ngfw_ecs_task(ngfw_id=42, command=["ngfw", "provision"])

        assert result is None

    def test_returns_none_when_subnet_ids_whitespace(self, settings):
        """Function returns None when PULUMI_PRIVATE_SUBNET_IDS is only whitespace."""
        from engine.ecs import _start_ngfw_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.PULUMI_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.PULUMI_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.PULUMI_PRIVATE_SUBNET_IDS = "   ,   ,   "

        result = _start_ngfw_ecs_task(ngfw_id=42, command=["ngfw", "provision"])

        assert result is None

    # -------------------------------------------------------------------------
    # Input validation
    # -------------------------------------------------------------------------

    def test_raises_when_ngfw_id_is_none(self, settings):
        """Function raises error when ngfw_id is None."""
        from engine.ecs import _start_ngfw_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.PULUMI_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.PULUMI_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.PULUMI_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        with pytest.raises((TypeError, ValueError)):
            _start_ngfw_ecs_task(ngfw_id=None, command=["ngfw", "provision"])

    def test_raises_when_ngfw_id_is_negative(self, settings):
        """Function raises error when ngfw_id is negative."""
        from engine.ecs import _start_ngfw_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.PULUMI_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.PULUMI_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.PULUMI_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        with pytest.raises((TypeError, ValueError)):
            _start_ngfw_ecs_task(ngfw_id=-1, command=["ngfw", "provision"])

    def test_raises_when_ngfw_id_is_string(self, settings):
        """Function raises error when ngfw_id is a string."""
        from engine.ecs import _start_ngfw_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.PULUMI_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.PULUMI_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.PULUMI_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        with pytest.raises((TypeError, ValueError)):
            _start_ngfw_ecs_task(ngfw_id="42", command=["ngfw", "provision"])

    def test_raises_when_command_is_none(self, settings):
        """Function raises error when command is None."""
        from engine.ecs import _start_ngfw_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.PULUMI_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.PULUMI_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.PULUMI_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        with pytest.raises((TypeError, ValueError)):
            _start_ngfw_ecs_task(ngfw_id=42, command=None)

    def test_raises_when_command_is_empty_list(self, settings):
        """Function raises error when command is empty list."""
        from engine.ecs import _start_ngfw_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.PULUMI_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.PULUMI_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.PULUMI_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        with pytest.raises((TypeError, ValueError)):
            _start_ngfw_ecs_task(ngfw_id=42, command=[])

    def test_raises_when_command_is_string(self, settings):
        """Function raises error when command is a string instead of list."""
        from engine.ecs import _start_ngfw_ecs_task

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.PULUMI_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.PULUMI_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.PULUMI_PRIVATE_SUBNET_IDS = "subnet-1,subnet-2"

        with pytest.raises((TypeError, ValueError)):
            _start_ngfw_ecs_task(ngfw_id=42, command="ngfw provision")

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
                {"Error": {"Code": "ClusterNotFound", "Message": "Cluster not found"}},
                "RunTask",
            )
            mock_get_client.return_value = mock_ecs

            with pytest.raises(ClientError):
                _start_ngfw_ecs_task(ngfw_id=42, command=["ngfw", "provision"])

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
                _start_ngfw_ecs_task(ngfw_id=42, command=["ngfw", "provision"])

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
            _start_ngfw_ecs_task(ngfw_id=42, command=["ngfw", "provision"])

        log_text = caplog.text.lower()
        assert "warning" in log_text or "incomplete" in log_text or "skipping" in log_text

    def test_logs_info_on_success(self, settings, caplog):
        """Function logs INFO when task starts successfully."""
        from engine.ecs import _start_ngfw_ecs_task

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

            _start_ngfw_ecs_task(ngfw_id=42, command=["ngfw", "provision"])

        assert "42" in caplog.text or "ngfw_id" in caplog.text.lower()

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
                {"Error": {"Code": "ClusterNotFound", "Message": "Cluster not found"}},
                "RunTask",
            )
            mock_get_client.return_value = mock_ecs

            _start_ngfw_ecs_task(ngfw_id=42, command=["ngfw", "provision"])

        assert "error" in caplog.text.lower() or "failed" in caplog.text.lower()
