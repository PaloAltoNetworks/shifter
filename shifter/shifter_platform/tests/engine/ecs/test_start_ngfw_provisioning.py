"""Tests for start_ngfw_provisioning() function."""

import logging
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError


class TestStartNgfwProvisioning:
    """Tests for start_ngfw_provisioning() public function.

    Contract:
    - Inputs: ngfw_id (int)
    - Outputs: ECS task ARN (str) if successful, None if ECS not configured
    - Side effects: Calls _validate_ngfw_id, then _start_ngfw_ecs_task with provision command
    - Errors: Propagates TypeError/ValueError from validation, ClientError from ECS
    - Logging: Delegates to _start_ngfw_ecs_task
    """

    # -------------------------------------------------------------------------
    # Happy path - function succeeds
    # -------------------------------------------------------------------------

    def test_returns_task_arn_on_success(self, settings):
        """Function returns ECS task ARN when provisioning starts."""
        from engine.ecs import start_ngfw_provisioning

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

            result = start_ngfw_provisioning(ngfw_id=42)

            assert result == "arn:aws:ecs:us-east-2:123456789:task/test/abc123"

    def test_calls_validate_ngfw_id(self, settings):
        """Function calls _validate_ngfw_id before starting task."""
        from engine.ecs import start_ngfw_provisioning

        with (
            patch("engine.ecs._validate_ngfw_id") as mock_validate,
            patch("engine.ecs._start_ngfw_ecs_task") as mock_start,
        ):
            mock_start.return_value = "arn:aws:ecs:task/123"

            start_ngfw_provisioning(ngfw_id=42)

            mock_validate.assert_called_once_with(42)

    def test_calls_start_ngfw_ecs_task_with_provision_command(self, settings):
        """Function calls _start_ngfw_ecs_task with 'ngfw provision' command."""
        from engine.ecs import start_ngfw_provisioning

        with patch("engine.ecs._start_ngfw_ecs_task") as mock_start:
            mock_start.return_value = "arn:aws:ecs:task/123"

            start_ngfw_provisioning(ngfw_id=42)

            mock_start.assert_called_once_with(42, ["ngfw", "provision", "--user-ngfw-id", "42"])

    def test_command_includes_ngfw_id_as_string(self, settings):
        """Function passes ngfw_id as string in command arguments."""
        from engine.ecs import start_ngfw_provisioning

        with patch("engine.ecs._start_ngfw_ecs_task") as mock_start:
            mock_start.return_value = "arn:aws:ecs:task/123"

            start_ngfw_provisioning(ngfw_id=999)

            call_args = mock_start.call_args
            command = call_args[0][1]
            assert "999" in command
            assert command == ["ngfw", "provision", "--user-ngfw-id", "999"]

    def test_accepts_zero_as_ngfw_id(self, settings):
        """Function accepts 0 as valid ngfw_id."""
        from engine.ecs import start_ngfw_provisioning

        with patch("engine.ecs._start_ngfw_ecs_task") as mock_start:
            mock_start.return_value = "arn:aws:ecs:task/123"

            result = start_ngfw_provisioning(ngfw_id=0)

            assert result == "arn:aws:ecs:task/123"
            mock_start.assert_called_once_with(0, ["ngfw", "provision", "--user-ngfw-id", "0"])

    def test_accepts_large_ngfw_id(self, settings):
        """Function accepts large ngfw_id values."""
        from engine.ecs import start_ngfw_provisioning

        with patch("engine.ecs._start_ngfw_ecs_task") as mock_start:
            mock_start.return_value = "arn:aws:ecs:task/123"

            result = start_ngfw_provisioning(ngfw_id=999999999)

            assert result == "arn:aws:ecs:task/123"

    # -------------------------------------------------------------------------
    # Configuration - ECS not configured
    # -------------------------------------------------------------------------

    def test_returns_none_when_ecs_not_configured(self, settings):
        """Function returns None when ECS is not configured."""
        from engine.ecs import start_ngfw_provisioning

        settings.AWS_REGION = "us-east-2"
        if hasattr(settings, "PULUMI_ECS_CLUSTER_ARN"):
            delattr(settings, "PULUMI_ECS_CLUSTER_ARN")

        result = start_ngfw_provisioning(ngfw_id=42)

        assert result is None

    def test_returns_none_when_task_definition_missing(self, settings):
        """Function returns None when task definition is missing."""
        from engine.ecs import start_ngfw_provisioning

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        if hasattr(settings, "PULUMI_TASK_DEFINITION_ARN"):
            delattr(settings, "PULUMI_TASK_DEFINITION_ARN")

        result = start_ngfw_provisioning(ngfw_id=42)

        assert result is None

    def test_returns_none_when_subnet_ids_empty(self, settings):
        """Function returns None when subnet IDs are empty."""
        from engine.ecs import start_ngfw_provisioning

        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:us-east-2:123456789:cluster/test"
        settings.PULUMI_TASK_DEFINITION_ARN = "arn:aws:ecs:us-east-2:123456789:task-definition/test:1"
        settings.PULUMI_ECS_SECURITY_GROUP_ID = "sg-12345678"
        settings.PULUMI_PRIVATE_SUBNET_IDS = ""

        result = start_ngfw_provisioning(ngfw_id=42)

        assert result is None

    # -------------------------------------------------------------------------
    # Input validation - inherited from _validate_ngfw_id
    # -------------------------------------------------------------------------

    def test_raises_type_error_when_ngfw_id_is_none(self, settings):
        """Function raises TypeError when ngfw_id is None."""
        from engine.ecs import start_ngfw_provisioning

        with pytest.raises(TypeError):
            start_ngfw_provisioning(ngfw_id=None)

    def test_raises_value_error_when_ngfw_id_is_negative(self, settings):
        """Function raises ValueError when ngfw_id is negative."""
        from engine.ecs import start_ngfw_provisioning

        with pytest.raises(ValueError):
            start_ngfw_provisioning(ngfw_id=-1)

    def test_raises_type_error_when_ngfw_id_is_string(self, settings):
        """Function raises TypeError when ngfw_id is a string."""
        from engine.ecs import start_ngfw_provisioning

        with pytest.raises(TypeError):
            start_ngfw_provisioning(ngfw_id="42")

    def test_raises_type_error_when_ngfw_id_is_float(self, settings):
        """Function raises TypeError when ngfw_id is a float."""
        from engine.ecs import start_ngfw_provisioning

        with pytest.raises(TypeError):
            start_ngfw_provisioning(ngfw_id=42.0)

    def test_raises_type_error_when_ngfw_id_is_bool(self, settings):
        """Function raises TypeError when ngfw_id is a boolean."""
        from engine.ecs import start_ngfw_provisioning

        with pytest.raises(TypeError):
            start_ngfw_provisioning(ngfw_id=True)

    def test_raises_type_error_when_ngfw_id_is_list(self, settings):
        """Function raises TypeError when ngfw_id is a list."""
        from engine.ecs import start_ngfw_provisioning

        with pytest.raises(TypeError):
            start_ngfw_provisioning(ngfw_id=[42])

    def test_raises_type_error_when_ngfw_id_is_dict(self, settings):
        """Function raises TypeError when ngfw_id is a dict."""
        from engine.ecs import start_ngfw_provisioning

        with pytest.raises(TypeError):
            start_ngfw_provisioning(ngfw_id={"id": 42})

    # -------------------------------------------------------------------------
    # Error handling - propagates errors
    # -------------------------------------------------------------------------

    def test_propagates_client_error_from_ecs(self, settings):
        """Function propagates ClientError from _start_ngfw_ecs_task."""
        from engine.ecs import start_ngfw_provisioning

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
                start_ngfw_provisioning(ngfw_id=42)

    def test_propagates_type_error_from_validation(self, settings):
        """Function propagates TypeError from _validate_ngfw_id."""
        from engine.ecs import start_ngfw_provisioning

        with pytest.raises(TypeError) as exc_info:
            start_ngfw_provisioning(ngfw_id=None)

        assert "integer" in str(exc_info.value).lower() or "None" in str(exc_info.value)

    def test_propagates_value_error_from_validation(self, settings):
        """Function propagates ValueError from _validate_ngfw_id."""
        from engine.ecs import start_ngfw_provisioning

        with pytest.raises(ValueError) as exc_info:
            start_ngfw_provisioning(ngfw_id=-1)

        assert "positive" in str(exc_info.value).lower() or "negative" in str(exc_info.value).lower()

    def test_validation_runs_before_ecs_call(self, settings):
        """Validation runs before attempting ECS call."""
        from engine.ecs import start_ngfw_provisioning

        with patch("engine.ecs._start_ngfw_ecs_task") as mock_start:
            with pytest.raises(TypeError):
                start_ngfw_provisioning(ngfw_id=None)

            mock_start.assert_not_called()

    # -------------------------------------------------------------------------
    # Logging - delegates to _start_ngfw_ecs_task
    # -------------------------------------------------------------------------

    def test_logs_info_on_success(self, settings, caplog):
        """Function logs INFO when provisioning starts."""
        from engine.ecs import start_ngfw_provisioning

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

            start_ngfw_provisioning(ngfw_id=42)

        assert "42" in caplog.text or "ngfw" in caplog.text.lower()

    def test_logs_warning_when_config_incomplete(self, settings, caplog):
        """Function logs WARNING when ECS configuration is incomplete."""
        from engine.ecs import start_ngfw_provisioning

        settings.AWS_REGION = "us-east-2"
        if hasattr(settings, "PULUMI_ECS_CLUSTER_ARN"):
            delattr(settings, "PULUMI_ECS_CLUSTER_ARN")

        with caplog.at_level(logging.WARNING, logger="engine.ecs"):
            start_ngfw_provisioning(ngfw_id=42)

        assert "incomplete" in caplog.text.lower() or "skipping" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Side effects - validation then ECS call
    # -------------------------------------------------------------------------

    def test_validation_called_before_start_task(self, settings):
        """Validation is called before _start_ngfw_ecs_task."""
        from engine.ecs import start_ngfw_provisioning

        call_order = []

        def track_validate(ngfw_id):
            call_order.append("validate")

        def track_start(ngfw_id, command):
            call_order.append("start")
            return "arn:aws:ecs:task/123"

        with (
            patch("engine.ecs._validate_ngfw_id", side_effect=track_validate),
            patch("engine.ecs._start_ngfw_ecs_task", side_effect=track_start),
        ):
            start_ngfw_provisioning(ngfw_id=42)

        assert call_order == ["validate", "start"]

    def test_does_not_call_start_task_if_validation_fails(self, settings):
        """Function does not call _start_ngfw_ecs_task if validation fails."""
        from engine.ecs import start_ngfw_provisioning

        with patch("engine.ecs._start_ngfw_ecs_task") as mock_start:
            with pytest.raises(ValueError):
                start_ngfw_provisioning(ngfw_id=-1)

            mock_start.assert_not_called()

    # -------------------------------------------------------------------------
    # Boundary conditions
    # -------------------------------------------------------------------------

    def test_boundary_zero_succeeds(self, settings):
        """Zero is a valid boundary value."""
        from engine.ecs import start_ngfw_provisioning

        with patch("engine.ecs._start_ngfw_ecs_task") as mock_start:
            mock_start.return_value = "arn:aws:ecs:task/123"

            result = start_ngfw_provisioning(ngfw_id=0)

            assert result == "arn:aws:ecs:task/123"

    def test_boundary_one_succeeds(self, settings):
        """One is typical first valid ID."""
        from engine.ecs import start_ngfw_provisioning

        with patch("engine.ecs._start_ngfw_ecs_task") as mock_start:
            mock_start.return_value = "arn:aws:ecs:task/123"

            result = start_ngfw_provisioning(ngfw_id=1)

            assert result == "arn:aws:ecs:task/123"

    def test_boundary_negative_one_fails(self, settings):
        """Negative one is invalid boundary."""
        from engine.ecs import start_ngfw_provisioning

        with pytest.raises(ValueError):
            start_ngfw_provisioning(ngfw_id=-1)
