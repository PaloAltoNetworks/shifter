"""Tests for AWSExecutor - TDD: Write tests first, all must fail initially.

AWSExecutor wraps boto3 for AWS API calls, providing a consistent
interface for the orchestrators to interact with AWS services.
"""

import json
from unittest.mock import MagicMock, patch

import pytest


class TestAWSExecutorInit:
    """Test AWSExecutor initialization."""

    def test_init_creates_default_session(self):
        """AWSExecutor creates boto3 session if none provided."""
        from executors.aws_executor import AWSExecutor

        with patch("executors.aws_executor.boto3") as mock_boto3:
            mock_session = MagicMock()
            mock_boto3.Session.return_value = mock_session

            executor = AWSExecutor()

            mock_boto3.Session.assert_called_once()
            assert executor.session is mock_session

    def test_init_uses_provided_session(self):
        """AWSExecutor uses injected session for DI."""
        from executors.aws_executor import AWSExecutor

        mock_session = MagicMock()
        executor = AWSExecutor(session=mock_session)

        assert executor.session is mock_session

    def test_init_accepts_region_name(self):
        """AWSExecutor passes region_name to session."""
        from executors.aws_executor import AWSExecutor

        with patch("executors.aws_executor.boto3") as mock_boto3:
            mock_session = MagicMock()
            mock_boto3.Session.return_value = mock_session

            executor = AWSExecutor(region_name="us-west-2")

            mock_boto3.Session.assert_called_once_with(region_name="us-west-2")


class TestAWSExecutorRunCommand:
    """Test AWSExecutor.run_command method."""

    def test_run_command_calls_correct_service(self):
        """run_command creates client for specified service."""
        from executors.aws_executor import AWSExecutor

        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.describe_instances.return_value = {"Reservations": []}

        executor = AWSExecutor(session=mock_session)
        executor.run_command("ec2", "describe_instances")

        mock_session.client.assert_called_with("ec2")

    def test_run_command_calls_correct_method(self):
        """run_command calls the specified method on the client."""
        from executors.aws_executor import AWSExecutor

        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.list_buckets.return_value = {"Buckets": []}

        executor = AWSExecutor(session=mock_session)
        executor.run_command("s3", "list_buckets")

        mock_client.list_buckets.assert_called_once()

    def test_run_command_passes_kwargs(self):
        """run_command passes kwargs to the AWS method."""
        from executors.aws_executor import AWSExecutor

        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.describe_instances.return_value = {"Reservations": []}

        executor = AWSExecutor(session=mock_session)
        executor.run_command(
            "ec2",
            "describe_instances",
            InstanceIds=["i-12345"],
            Filters=[{"Name": "instance-state-name", "Values": ["running"]}],
        )

        mock_client.describe_instances.assert_called_once_with(
            InstanceIds=["i-12345"],
            Filters=[{"Name": "instance-state-name", "Values": ["running"]}],
        )

    def test_run_command_returns_command_result_on_success(self):
        """run_command returns CommandResult on success."""
        from executors.aws_executor import AWSExecutor
        from executors.base import CommandResult

        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.describe_instances.return_value = {
            "Reservations": [{"Instances": [{"InstanceId": "i-12345"}]}]
        }

        executor = AWSExecutor(session=mock_session)
        result = executor.run_command("ec2", "describe_instances")

        assert isinstance(result, CommandResult)
        assert result.success is True
        assert "i-12345" in result.stdout

    def test_run_command_stdout_is_json(self):
        """run_command stdout contains JSON-serialized response."""
        from executors.aws_executor import AWSExecutor

        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        response = {"Buckets": [{"Name": "test-bucket"}]}
        mock_client.list_buckets.return_value = response

        executor = AWSExecutor(session=mock_session)
        result = executor.run_command("s3", "list_buckets")

        # stdout should be parseable JSON
        parsed = json.loads(result.stdout)
        assert parsed == response


class TestAWSExecutorErrorHandling:
    """Test AWSExecutor error handling."""

    def test_run_command_client_error_returns_failure(self):
        """run_command returns failure on ClientError."""
        from botocore.exceptions import ClientError
        from executors.aws_executor import AWSExecutor
        from executors.base import CommandResult

        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.describe_instances.side_effect = ClientError(
            {"Error": {"Code": "InvalidInstanceId", "Message": "Not found"}},
            "DescribeInstances",
        )

        executor = AWSExecutor(session=mock_session)
        result = executor.run_command("ec2", "describe_instances", InstanceIds=["i-invalid"])

        assert isinstance(result, CommandResult)
        assert result.success is False
        assert "InvalidInstanceId" in result.stderr

    def test_run_command_generic_error_returns_failure(self):
        """run_command returns failure on generic exceptions."""
        from executors.aws_executor import AWSExecutor
        from executors.base import CommandResult

        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.describe_instances.side_effect = Exception("Connection timeout")

        executor = AWSExecutor(session=mock_session)
        result = executor.run_command("ec2", "describe_instances")

        assert isinstance(result, CommandResult)
        assert result.success is False
        assert "Connection timeout" in result.stderr


class TestAWSExecutorProtocolCompliance:
    """Test that AWSExecutor implements Executor protocol."""

    def test_has_run_command_method(self):
        """AWSExecutor has run_command method."""
        from executors.aws_executor import AWSExecutor

        assert hasattr(AWSExecutor, "run_command")
        assert callable(getattr(AWSExecutor, "run_command"))

    def test_run_command_signature(self):
        """AWSExecutor.run_command has expected signature."""
        from executors.aws_executor import AWSExecutor
        import inspect

        sig = inspect.signature(AWSExecutor.run_command)
        param_names = list(sig.parameters.keys())

        # Should have self, service, method, and **kwargs
        assert "service" in param_names
        assert "method" in param_names


class TestAWSExecutorGetClient:
    """Test AWSExecutor.get_client method."""

    def test_get_client_returns_boto3_client(self):
        """get_client returns a boto3 service client."""
        from executors.aws_executor import AWSExecutor

        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client

        executor = AWSExecutor(session=mock_session)
        client = executor.get_client("ec2")

        mock_session.client.assert_called_with("ec2")
        assert client is mock_client

    def test_get_client_caches_clients(self):
        """get_client caches clients for reuse."""
        from executors.aws_executor import AWSExecutor

        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client

        executor = AWSExecutor(session=mock_session)

        # Get same client twice
        client1 = executor.get_client("ec2")
        client2 = executor.get_client("ec2")

        # Should only create client once
        assert mock_session.client.call_count == 1
        assert client1 is client2
