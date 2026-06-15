"""Tests for AWSExecutor - focused on actual logic, not mock verification.

Tests error handling, caching, validation, and business logic.
Trivial mock-calling tests have been removed.
"""

import json
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError, WaiterError

from executors.aws_executor import AWSExecutor
from executors.base import CommandResult


class TestAWSExecutorClientCaching:
    """Test client caching behavior."""

    def test_get_client_caches_clients(self):
        """get_client should cache and reuse clients for the same service."""
        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client

        executor = AWSExecutor(session=mock_session)

        client1 = executor.get_client("ec2")
        client2 = executor.get_client("ec2")

        # Should only create client once
        assert mock_session.client.call_count == 1
        assert client1 is client2

    def test_get_client_creates_separate_clients_per_service(self):
        """get_client should create separate clients for different services."""
        mock_session = MagicMock()
        mock_session.client.side_effect = lambda svc: MagicMock(name=svc)

        executor = AWSExecutor(session=mock_session)

        ec2_client = executor.get_client("ec2")
        s3_client = executor.get_client("s3")

        assert mock_session.client.call_count == 2
        assert ec2_client is not s3_client


class TestAWSExecutorRunCommandErrorHandling:
    """Test run_command error handling."""

    def test_run_command_returns_command_result_on_success(self):
        """run_command should return CommandResult with success=True."""
        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.describe_instances.return_value = {"Reservations": [{"Instances": [{"InstanceId": "i-12345"}]}]}

        executor = AWSExecutor(session=mock_session)
        result = executor.run_command("ec2", "describe_instances")

        assert isinstance(result, CommandResult)
        assert result.success is True
        assert "i-12345" in result.stdout

    def test_run_command_stdout_is_valid_json(self):
        """run_command stdout should contain JSON-serialized response."""
        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        response = {"Buckets": [{"Name": "test-bucket"}]}
        mock_client.list_buckets.return_value = response

        executor = AWSExecutor(session=mock_session)
        result = executor.run_command("s3", "list_buckets")

        parsed = json.loads(result.stdout)
        assert parsed == response

    def test_run_command_client_error_returns_failure_with_error_code(self):
        """run_command should return failure with error code on ClientError."""
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

    def test_run_command_generic_exception_returns_failure(self):
        """run_command should return failure on generic exceptions."""
        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.describe_instances.side_effect = Exception("Connection timeout")

        executor = AWSExecutor(session=mock_session)
        result = executor.run_command("ec2", "describe_instances")

        assert isinstance(result, CommandResult)
        assert result.success is False
        assert "Connection timeout" in result.stderr


class TestAWSExecutorWaiterErrorHandling:
    """Test waiter-based methods error handling."""

    def test_wait_for_running_configures_waiter_with_timeout(self):
        """wait_for_running should configure WaiterConfig based on timeout."""
        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_waiter = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.get_waiter.return_value = mock_waiter

        executor = AWSExecutor(session=mock_session)
        result = executor.wait_for_running("i-12345", timeout=600)

        call_kwargs = mock_waiter.wait.call_args[1]
        assert "WaiterConfig" in call_kwargs
        assert result.success is True

    def test_wait_for_running_handles_waiter_timeout(self):
        """wait_for_running should handle WaiterError gracefully."""
        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_waiter = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.get_waiter.return_value = mock_waiter
        mock_waiter.wait.side_effect = WaiterError("instance_running", "timeout", {})

        executor = AWSExecutor(session=mock_session)
        result = executor.wait_for_running("i-12345")

        assert result.success is False
        assert "timeout" in result.stderr.lower() or "waiter" in result.stderr.lower()

    def test_wait_for_stopped_handles_waiter_timeout(self):
        """wait_for_stopped should handle WaiterError gracefully."""
        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_waiter = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.get_waiter.return_value = mock_waiter
        mock_waiter.wait.side_effect = WaiterError("instance_stopped", "timeout", {})

        executor = AWSExecutor(session=mock_session)
        result = executor.wait_for_stopped("i-12345")

        assert result.success is False


class TestAWSExecutorSpecificBehavior:
    """Test specific behavior requirements."""

    def test_create_endpoint_uses_gateway_load_balancer_type(self):
        """create_endpoint should use GatewayLoadBalancer endpoint type."""
        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.create_vpc_endpoint.return_value = {"VpcEndpoint": {"VpcEndpointId": "vpce-12345"}}

        executor = AWSExecutor(session=mock_session)
        executor.create_endpoint(
            vpc_id="vpc-12345",
            service_name="com.amazonaws.vpce.us-east-1.vpce-svc-12345",
            subnet_ids=["subnet-12345"],
        )

        call_kwargs = mock_client.create_vpc_endpoint.call_args[1]
        assert call_kwargs["VpcEndpointType"] == "GatewayLoadBalancer"

    def test_start_instance_handles_client_error(self):
        """start_instance should handle ClientError with proper error message."""
        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.start_instances.side_effect = ClientError(
            {"Error": {"Code": "InvalidInstanceID.NotFound", "Message": "Instance not found"}},
            "StartInstances",
        )

        executor = AWSExecutor(session=mock_session)
        result = executor.start_instance("i-invalid")

        assert result.success is False
        assert "InvalidInstanceID" in result.stderr


class TestAWSExecutorPollingLogic:
    """Test polling-based methods."""

    def test_wait_for_endpoint_available_polls_until_available(self):
        """wait_for_endpoint_available should poll until state is 'available'."""
        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        # First call returns pending, second returns available
        mock_client.describe_vpc_endpoints.side_effect = [
            {"VpcEndpoints": [{"VpcEndpointId": "vpce-12345", "State": "pending"}]},
            {"VpcEndpoints": [{"VpcEndpointId": "vpce-12345", "State": "available"}]},
        ]

        executor = AWSExecutor(session=mock_session)
        with patch("executors._aws_executor_vpc_endpoints.time.sleep"):  # Skip actual sleep
            result = executor.wait_for_endpoint_available("vpce-12345", timeout=60)

        assert result.success is True
        assert mock_client.describe_vpc_endpoints.call_count >= 1

    def test_wait_for_endpoint_available_fails_on_terminal_state(self):
        """wait_for_endpoint_available should fail on terminal states like 'failed'."""
        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.describe_vpc_endpoints.return_value = {
            "VpcEndpoints": [{"VpcEndpointId": "vpce-12345", "State": "failed"}]
        }

        executor = AWSExecutor(session=mock_session)
        result = executor.wait_for_endpoint_available("vpce-12345", timeout=60)

        assert result.success is False
        assert "terminal state" in result.stderr.lower() or "failed" in result.stderr.lower()


class TestAWSExecutorExecuteActionValidation:
    """Test execute_action dispatcher validation."""

    def test_execute_action_unknown_action_returns_failure(self):
        """execute_action should return failure for unknown action names."""
        mock_session = MagicMock()
        executor = AWSExecutor(session=mock_session)

        result = executor.execute_action("unknown_action", {})

        assert result.success is False
        assert "Unknown action" in result.stderr

    def test_execute_action_missing_param_returns_failure(self):
        """execute_action should return failure when required param is missing."""
        mock_session = MagicMock()
        executor = AWSExecutor(session=mock_session)

        # start_instance requires instance_id
        result = executor.execute_action("start_instance", {})

        assert result.success is False
        assert "Missing required parameter" in result.stderr
        assert "instance_id" in result.stderr

    def test_execute_action_dispatches_with_correct_params(self):
        """execute_action should dispatch to correct method with extracted params."""
        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.start_instances.return_value = {"StartingInstances": [{"InstanceId": "i-12345"}]}

        executor = AWSExecutor(session=mock_session)
        context = {"instance_id": "i-12345"}
        result = executor.execute_action("start_instance", context)

        mock_client.start_instances.assert_called_once_with(InstanceIds=["i-12345"])
        assert result.success is True
