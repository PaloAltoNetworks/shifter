"""Tests for provisioner service (Step Functions integration)."""

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from django.test import override_settings


@pytest.fixture
def mock_range_v1():
    """Mock Range object with v1 provisioner."""
    mock_range = MagicMock()
    mock_range.provisioner_version = "v1"
    return mock_range


class TestStartProvisioning:
    @override_settings(PROVISION_STATE_MACHINE_ARN="")
    def test_returns_none_when_not_configured(self, mock_range_v1):
        """When ARN is not configured, returns None (local dev fallback)."""
        with patch("mission_control.models.Range") as MockRange:
            MockRange.objects.get.return_value = mock_range_v1

            from mission_control.services.provisioner import start_provisioning

            result = start_provisioning(range_id=1)
            assert result is None

    @override_settings(
        AWS_REGION="us-east-2",
        PROVISION_STATE_MACHINE_ARN=("arn:aws:states:us-east-2:123456789012:stateMachine:test-provision"),
    )
    def test_starts_execution_and_returns_arn(self, mock_range_v1):
        """Successfully starts Step Functions execution."""
        with (
            patch("mission_control.models.Range") as MockRange,
            patch("mission_control.services.provisioner.boto3.client") as mock_client,
        ):
            MockRange.objects.get.return_value = mock_range_v1
            mock_sfn = mock_client.return_value
            mock_sfn.start_execution.return_value = {
                "executionArn": ("arn:aws:states:us-east-2:123456789012:execution:test:abc123")
            }

            from mission_control.services.provisioner import start_provisioning

            result = start_provisioning(range_id=42)

            assert result == ("arn:aws:states:us-east-2:123456789012:execution:test:abc123")
            mock_sfn.start_execution.assert_called_once()
            call_args = mock_sfn.start_execution.call_args
            assert call_args.kwargs["stateMachineArn"] == (
                "arn:aws:states:us-east-2:123456789012:stateMachine:test-provision"
            )
            assert '"range_id": 42' in call_args.kwargs["input"]

    @override_settings(
        AWS_REGION="us-east-2",
        PROVISION_STATE_MACHINE_ARN=("arn:aws:states:us-east-2:123456789012:stateMachine:test-provision"),
    )
    def test_raises_on_client_error(self, mock_range_v1):
        """ClientError from AWS is propagated."""
        with (
            patch("mission_control.models.Range") as MockRange,
            patch("mission_control.services.provisioner.boto3.client") as mock_client,
        ):
            MockRange.objects.get.return_value = mock_range_v1
            mock_sfn = mock_client.return_value
            mock_sfn.start_execution.side_effect = ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}},
                "StartExecution",
            )

            from mission_control.services.provisioner import start_provisioning

            with pytest.raises(ClientError):
                start_provisioning(range_id=1)


class TestStartTeardown:
    @override_settings(TEARDOWN_STATE_MACHINE_ARN="")
    def test_returns_none_when_not_configured(self, mock_range_v1):
        """When ARN is not configured, returns None (local dev fallback)."""
        with patch("mission_control.models.Range") as MockRange:
            MockRange.objects.get.return_value = mock_range_v1

            from mission_control.services.provisioner import start_teardown

            result = start_teardown(range_id=1)
            assert result is None

    @override_settings(
        AWS_REGION="us-east-2",
        TEARDOWN_STATE_MACHINE_ARN=("arn:aws:states:us-east-2:123456789012:stateMachine:test-teardown"),
    )
    def test_starts_execution_and_returns_arn(self, mock_range_v1):
        """Successfully starts Step Functions teardown execution."""
        with (
            patch("mission_control.models.Range") as MockRange,
            patch("mission_control.services.provisioner.boto3.client") as mock_client,
        ):
            MockRange.objects.get.return_value = mock_range_v1
            mock_sfn = mock_client.return_value
            mock_sfn.start_execution.return_value = {
                "executionArn": ("arn:aws:states:us-east-2:123456789012:execution:teardown:xyz789")
            }

            from mission_control.services.provisioner import start_teardown

            result = start_teardown(range_id=99)

            assert result == ("arn:aws:states:us-east-2:123456789012:execution:teardown:xyz789")
            mock_sfn.start_execution.assert_called_once()
            call_args = mock_sfn.start_execution.call_args
            assert call_args.kwargs["stateMachineArn"] == (
                "arn:aws:states:us-east-2:123456789012:stateMachine:test-teardown"
            )
            assert '"range_id": 99' in call_args.kwargs["input"]

    @override_settings(
        AWS_REGION="us-east-2",
        TEARDOWN_STATE_MACHINE_ARN=("arn:aws:states:us-east-2:123456789012:stateMachine:test-teardown"),
    )
    def test_raises_on_client_error(self, mock_range_v1):
        """ClientError from AWS is propagated."""
        with (
            patch("mission_control.models.Range") as MockRange,
            patch("mission_control.services.provisioner.boto3.client") as mock_client,
        ):
            MockRange.objects.get.return_value = mock_range_v1
            mock_sfn = mock_client.return_value
            mock_sfn.start_execution.side_effect = ClientError(
                {"Error": {"Code": "StateMachineDoesNotExist", "Message": "Not found"}},
                "StartExecution",
            )

            from mission_control.services.provisioner import start_teardown

            with pytest.raises(ClientError):
                start_teardown(range_id=1)


class TestGetExecutionStatus:
    @override_settings(AWS_REGION="us-east-2")
    def test_returns_none_for_empty_arn(self):
        """Returns None when no execution ARN provided."""
        from mission_control.services.provisioner import get_execution_status

        result = get_execution_status("")
        assert result is None

        result = get_execution_status(None)
        assert result is None

    @override_settings(AWS_REGION="us-east-2")
    def test_returns_status_info(self):
        """Returns execution status info from Step Functions."""
        from datetime import datetime

        with patch("mission_control.services.provisioner.boto3.client") as mock_client:
            mock_sfn = mock_client.return_value
            mock_sfn.describe_execution.return_value = {
                "status": "RUNNING",
                "startDate": datetime(2025, 1, 1, 12, 0, 0),
                "stopDate": None,
            }

            from mission_control.services.provisioner import get_execution_status

            arn = "arn:aws:states:us-east-2:123:execution:test:abc"
            result = get_execution_status(arn)

            assert result["status"] == "RUNNING"
            assert result["start_date"] == datetime(2025, 1, 1, 12, 0, 0)
            assert result["stop_date"] is None

    @override_settings(AWS_REGION="us-east-2")
    def test_returns_none_on_error(self):
        """Returns None when describe_execution fails."""
        with patch("mission_control.services.provisioner.boto3.client") as mock_client:
            mock_sfn = mock_client.return_value
            mock_sfn.describe_execution.side_effect = ClientError(
                {"Error": {"Code": "ExecutionDoesNotExist", "Message": "Not found"}},
                "DescribeExecution",
            )

            from mission_control.services.provisioner import get_execution_status

            arn = "arn:aws:states:us-east-2:123:execution:test:abc"
            result = get_execution_status(arn)
            assert result is None
