"""Tests for provisioner service (Step Functions integration)."""

from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError


@pytest.fixture
def mock_settings(settings):
    """Configure Step Functions ARNs for testing."""
    settings.AWS_REGION = "us-east-2"
    settings.PROVISION_STATE_MACHINE_ARN = "arn:aws:states:us-east-2:123456789012:stateMachine:test-provision"
    settings.TEARDOWN_STATE_MACHINE_ARN = "arn:aws:states:us-east-2:123456789012:stateMachine:test-teardown"
    return settings


@pytest.fixture
def mock_sfn_client():
    """Create a mock Step Functions client."""
    with patch("mission_control.services.provisioner.boto3.client") as mock_client:
        yield mock_client.return_value


class TestStartProvisioning:
    def test_returns_none_when_not_configured(self, settings):
        """When ARN is not configured, returns None (local dev fallback)."""
        settings.PROVISION_STATE_MACHINE_ARN = ""

        from mission_control.services.provisioner import start_provisioning

        result = start_provisioning(range_id=1)
        assert result is None

    def test_starts_execution_and_returns_arn(self, mock_settings, mock_sfn_client):
        """Successfully starts Step Functions execution."""
        mock_sfn_client.start_execution.return_value = {
            "executionArn": "arn:aws:states:us-east-2:123456789012:execution:test:abc123"
        }

        from mission_control.services.provisioner import start_provisioning

        result = start_provisioning(range_id=42)

        assert result == "arn:aws:states:us-east-2:123456789012:execution:test:abc123"
        mock_sfn_client.start_execution.assert_called_once()
        call_args = mock_sfn_client.start_execution.call_args
        assert call_args.kwargs["stateMachineArn"] == mock_settings.PROVISION_STATE_MACHINE_ARN
        assert '"range_id": 42' in call_args.kwargs["input"]

    def test_raises_on_client_error(self, mock_settings, mock_sfn_client):
        """ClientError from AWS is propagated."""
        mock_sfn_client.start_execution.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}},
            "StartExecution",
        )

        from mission_control.services.provisioner import start_provisioning

        with pytest.raises(ClientError):
            start_provisioning(range_id=1)


class TestStartTeardown:
    def test_returns_none_when_not_configured(self, settings):
        """When ARN is not configured, returns None (local dev fallback)."""
        settings.TEARDOWN_STATE_MACHINE_ARN = ""

        from mission_control.services.provisioner import start_teardown

        result = start_teardown(range_id=1)
        assert result is None

    def test_starts_execution_and_returns_arn(self, mock_settings, mock_sfn_client):
        """Successfully starts Step Functions teardown execution."""
        mock_sfn_client.start_execution.return_value = {
            "executionArn": "arn:aws:states:us-east-2:123456789012:execution:teardown:xyz789"
        }

        from mission_control.services.provisioner import start_teardown

        result = start_teardown(range_id=99)

        assert result == "arn:aws:states:us-east-2:123456789012:execution:teardown:xyz789"
        mock_sfn_client.start_execution.assert_called_once()
        call_args = mock_sfn_client.start_execution.call_args
        assert call_args.kwargs["stateMachineArn"] == mock_settings.TEARDOWN_STATE_MACHINE_ARN
        assert '"range_id": 99' in call_args.kwargs["input"]

    def test_raises_on_client_error(self, mock_settings, mock_sfn_client):
        """ClientError from AWS is propagated."""
        mock_sfn_client.start_execution.side_effect = ClientError(
            {"Error": {"Code": "StateMachineDoesNotExist", "Message": "Not found"}},
            "StartExecution",
        )

        from mission_control.services.provisioner import start_teardown

        with pytest.raises(ClientError):
            start_teardown(range_id=1)


class TestGetExecutionStatus:
    def test_returns_none_for_empty_arn(self, mock_settings):
        """Returns None when no execution ARN provided."""
        from mission_control.services.provisioner import get_execution_status

        result = get_execution_status("")
        assert result is None

        result = get_execution_status(None)
        assert result is None

    def test_returns_status_info(self, mock_settings, mock_sfn_client):
        """Returns execution status info from Step Functions."""
        from datetime import datetime

        mock_sfn_client.describe_execution.return_value = {
            "status": "RUNNING",
            "startDate": datetime(2025, 1, 1, 12, 0, 0),
            "stopDate": None,
        }

        from mission_control.services.provisioner import get_execution_status

        result = get_execution_status("arn:aws:states:us-east-2:123:execution:test:abc")

        assert result["status"] == "RUNNING"
        assert result["start_date"] == datetime(2025, 1, 1, 12, 0, 0)
        assert result["stop_date"] is None

    def test_returns_none_on_error(self, mock_settings, mock_sfn_client):
        """Returns None when describe_execution fails."""
        mock_sfn_client.describe_execution.side_effect = ClientError(
            {"Error": {"Code": "ExecutionDoesNotExist", "Message": "Not found"}},
            "DescribeExecution",
        )

        from mission_control.services.provisioner import get_execution_status

        result = get_execution_status("arn:aws:states:us-east-2:123:execution:test:abc")
        assert result is None
