"""Tests for AWSExecutor - TDD: Write tests first, all must fail initially.

AWSExecutor wraps boto3 for AWS API calls, providing a consistent
interface for the orchestrators to interact with AWS services.
"""

import json
from unittest.mock import MagicMock, patch


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

            AWSExecutor(region_name="us-west-2")

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
        mock_client.describe_instances.return_value = {"Reservations": [{"Instances": [{"InstanceId": "i-12345"}]}]}

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
        assert callable(AWSExecutor.run_command)

    def test_run_command_signature(self):
        """AWSExecutor.run_command has expected signature."""
        import inspect

        from executors.aws_executor import AWSExecutor

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


# =============================================================================
# Phase 1 TDD: Specific Operation Methods
# =============================================================================


class TestAWSExecutorEC2StartInstance:
    """Test AWSExecutor.start_instance method."""

    def test_start_instance_exists(self):
        """AWSExecutor has start_instance method."""
        from executors.aws_executor import AWSExecutor

        assert hasattr(AWSExecutor, "start_instance")
        assert callable(AWSExecutor.start_instance)

    def test_start_instance_calls_ec2_start_instances(self):
        """start_instance calls EC2 StartInstances API."""
        from executors.aws_executor import AWSExecutor

        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.start_instances.return_value = {
            "StartingInstances": [{"InstanceId": "i-12345", "CurrentState": {"Name": "pending"}}]
        }

        executor = AWSExecutor(session=mock_session)
        result = executor.start_instance("i-12345")

        mock_client.start_instances.assert_called_once_with(InstanceIds=["i-12345"])
        assert result.success is True

    def test_start_instance_returns_command_result(self):
        """start_instance returns CommandResult."""
        from executors.aws_executor import AWSExecutor
        from executors.base import CommandResult

        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.start_instances.return_value = {"StartingInstances": [{"InstanceId": "i-12345"}]}

        executor = AWSExecutor(session=mock_session)
        result = executor.start_instance("i-12345")

        assert isinstance(result, CommandResult)

    def test_start_instance_handles_error(self):
        """start_instance handles errors gracefully."""
        from botocore.exceptions import ClientError

        from executors.aws_executor import AWSExecutor

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


class TestAWSExecutorEC2StopInstance:
    """Test AWSExecutor.stop_instance method."""

    def test_stop_instance_exists(self):
        """AWSExecutor has stop_instance method."""
        from executors.aws_executor import AWSExecutor

        assert hasattr(AWSExecutor, "stop_instance")
        assert callable(AWSExecutor.stop_instance)

    def test_stop_instance_calls_ec2_stop_instances(self):
        """stop_instance calls EC2 StopInstances API."""
        from executors.aws_executor import AWSExecutor

        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.stop_instances.return_value = {
            "StoppingInstances": [{"InstanceId": "i-12345", "CurrentState": {"Name": "stopping"}}]
        }

        executor = AWSExecutor(session=mock_session)
        result = executor.stop_instance("i-12345")

        mock_client.stop_instances.assert_called_once_with(InstanceIds=["i-12345"])
        assert result.success is True

    def test_stop_instance_returns_command_result(self):
        """stop_instance returns CommandResult."""
        from executors.aws_executor import AWSExecutor
        from executors.base import CommandResult

        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.stop_instances.return_value = {"StoppingInstances": [{"InstanceId": "i-12345"}]}

        executor = AWSExecutor(session=mock_session)
        result = executor.stop_instance("i-12345")

        assert isinstance(result, CommandResult)


class TestAWSExecutorEC2WaitForRunning:
    """Test AWSExecutor.wait_for_running method."""

    def test_wait_for_running_exists(self):
        """AWSExecutor has wait_for_running method."""
        from executors.aws_executor import AWSExecutor

        assert hasattr(AWSExecutor, "wait_for_running")
        assert callable(AWSExecutor.wait_for_running)

    def test_wait_for_running_uses_waiter(self):
        """wait_for_running uses EC2 waiter."""
        from executors.aws_executor import AWSExecutor

        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_waiter = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.get_waiter.return_value = mock_waiter

        executor = AWSExecutor(session=mock_session)
        result = executor.wait_for_running("i-12345")

        mock_client.get_waiter.assert_called_once_with("instance_running")
        mock_waiter.wait.assert_called_once()
        assert result.success is True

    def test_wait_for_running_accepts_timeout(self):
        """wait_for_running accepts timeout parameter."""
        from executors.aws_executor import AWSExecutor

        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_waiter = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.get_waiter.return_value = mock_waiter

        executor = AWSExecutor(session=mock_session)
        result = executor.wait_for_running("i-12345", timeout=600)

        # Waiter should be called with WaiterConfig
        call_kwargs = mock_waiter.wait.call_args[1]
        assert "WaiterConfig" in call_kwargs
        assert result.success is True

    def test_wait_for_running_handles_timeout_error(self):
        """wait_for_running handles waiter timeout."""
        from botocore.exceptions import WaiterError

        from executors.aws_executor import AWSExecutor

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


class TestAWSExecutorEC2WaitForStopped:
    """Test AWSExecutor.wait_for_stopped method."""

    def test_wait_for_stopped_exists(self):
        """AWSExecutor has wait_for_stopped method."""
        from executors.aws_executor import AWSExecutor

        assert hasattr(AWSExecutor, "wait_for_stopped")
        assert callable(AWSExecutor.wait_for_stopped)

    def test_wait_for_stopped_uses_waiter(self):
        """wait_for_stopped uses EC2 waiter."""
        from executors.aws_executor import AWSExecutor

        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_waiter = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.get_waiter.return_value = mock_waiter

        executor = AWSExecutor(session=mock_session)
        result = executor.wait_for_stopped("i-12345")

        mock_client.get_waiter.assert_called_once_with("instance_stopped")
        mock_waiter.wait.assert_called_once()
        assert result.success is True


class TestAWSExecutorEC2DescribeInstance:
    """Test AWSExecutor.describe_instance method."""

    def test_describe_instance_exists(self):
        """AWSExecutor has describe_instance method."""
        from executors.aws_executor import AWSExecutor

        assert hasattr(AWSExecutor, "describe_instance")
        assert callable(AWSExecutor.describe_instance)

    def test_describe_instance_calls_describe_instances(self):
        """describe_instance calls EC2 DescribeInstances API."""
        from executors.aws_executor import AWSExecutor

        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.describe_instances.return_value = {
            "Reservations": [{"Instances": [{"InstanceId": "i-12345", "State": {"Name": "running"}}]}]
        }

        executor = AWSExecutor(session=mock_session)
        result = executor.describe_instance("i-12345")

        mock_client.describe_instances.assert_called_once_with(InstanceIds=["i-12345"])
        assert result.success is True
        assert "i-12345" in result.stdout


class TestAWSExecutorGWLBRegisterTarget:
    """Test AWSExecutor.register_target method."""

    def test_register_target_exists(self):
        """AWSExecutor has register_target method."""
        from executors.aws_executor import AWSExecutor

        assert hasattr(AWSExecutor, "register_target")
        assert callable(AWSExecutor.register_target)

    def test_register_target_calls_elbv2_register_targets(self):
        """register_target calls ELBv2 RegisterTargets API."""
        from executors.aws_executor import AWSExecutor

        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.register_targets.return_value = {}

        executor = AWSExecutor(session=mock_session)
        result = executor.register_target(
            target_group_arn="arn:aws:elasticloadbalancing:us-east-1:123456789:targetgroup/tg-123",
            target_id="i-12345",
        )

        mock_client.register_targets.assert_called_once()
        assert result.success is True

    def test_register_target_passes_correct_params(self):
        """register_target passes correct parameters to API."""
        from executors.aws_executor import AWSExecutor

        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.register_targets.return_value = {}

        executor = AWSExecutor(session=mock_session)
        executor.register_target(
            target_group_arn="arn:aws:elasticloadbalancing:us-east-1:123456789:targetgroup/tg-123",
            target_id="eni-12345",
        )

        call_kwargs = mock_client.register_targets.call_args[1]
        assert call_kwargs["TargetGroupArn"] == "arn:aws:elasticloadbalancing:us-east-1:123456789:targetgroup/tg-123"
        assert {"Id": "eni-12345"} in call_kwargs["Targets"]


class TestAWSExecutorGWLBDeregisterTarget:
    """Test AWSExecutor.deregister_target method."""

    def test_deregister_target_exists(self):
        """AWSExecutor has deregister_target method."""
        from executors.aws_executor import AWSExecutor

        assert hasattr(AWSExecutor, "deregister_target")
        assert callable(AWSExecutor.deregister_target)

    def test_deregister_target_calls_elbv2_deregister_targets(self):
        """deregister_target calls ELBv2 DeregisterTargets API."""
        from executors.aws_executor import AWSExecutor

        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.deregister_targets.return_value = {}

        executor = AWSExecutor(session=mock_session)
        result = executor.deregister_target(
            target_group_arn="arn:aws:elasticloadbalancing:us-east-1:123456789:targetgroup/tg-123",
            target_id="eni-12345",
        )

        mock_client.deregister_targets.assert_called_once()
        assert result.success is True


class TestAWSExecutorVPCCreateEndpoint:
    """Test AWSExecutor.create_endpoint method."""

    def test_create_endpoint_exists(self):
        """AWSExecutor has create_endpoint method."""
        from executors.aws_executor import AWSExecutor

        assert hasattr(AWSExecutor, "create_endpoint")
        assert callable(AWSExecutor.create_endpoint)

    def test_create_endpoint_calls_create_vpc_endpoint(self):
        """create_endpoint calls EC2 CreateVpcEndpoint API."""
        from executors.aws_executor import AWSExecutor

        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.create_vpc_endpoint.return_value = {
            "VpcEndpoint": {"VpcEndpointId": "vpce-12345", "State": "pending"}
        }

        executor = AWSExecutor(session=mock_session)
        result = executor.create_endpoint(
            vpc_id="vpc-12345",
            service_name="com.amazonaws.vpce.us-east-1.vpce-svc-12345",
            subnet_ids=["subnet-12345"],
        )

        mock_client.create_vpc_endpoint.assert_called_once()
        assert result.success is True
        assert "vpce-12345" in result.stdout

    def test_create_endpoint_uses_gateway_load_balancer_type(self):
        """create_endpoint uses GatewayLoadBalancer endpoint type."""
        from executors.aws_executor import AWSExecutor

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


class TestAWSExecutorVPCDeleteEndpoint:
    """Test AWSExecutor.delete_endpoint method."""

    def test_delete_endpoint_exists(self):
        """AWSExecutor has delete_endpoint method."""
        from executors.aws_executor import AWSExecutor

        assert hasattr(AWSExecutor, "delete_endpoint")
        assert callable(AWSExecutor.delete_endpoint)

    def test_delete_endpoint_calls_delete_vpc_endpoints(self):
        """delete_endpoint calls EC2 DeleteVpcEndpoints API."""
        from executors.aws_executor import AWSExecutor

        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.delete_vpc_endpoints.return_value = {"Unsuccessful": []}

        executor = AWSExecutor(session=mock_session)
        result = executor.delete_endpoint("vpce-12345")

        mock_client.delete_vpc_endpoints.assert_called_once_with(VpcEndpointIds=["vpce-12345"])
        assert result.success is True


class TestAWSExecutorVPCDescribeEndpoint:
    """Test AWSExecutor.describe_endpoint method."""

    def test_describe_endpoint_exists(self):
        """AWSExecutor has describe_endpoint method."""
        from executors.aws_executor import AWSExecutor

        assert hasattr(AWSExecutor, "describe_endpoint")
        assert callable(AWSExecutor.describe_endpoint)

    def test_describe_endpoint_calls_describe_vpc_endpoints(self):
        """describe_endpoint calls EC2 DescribeVpcEndpoints API."""
        from executors.aws_executor import AWSExecutor

        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.describe_vpc_endpoints.return_value = {
            "VpcEndpoints": [{"VpcEndpointId": "vpce-12345", "State": "available"}]
        }

        executor = AWSExecutor(session=mock_session)
        result = executor.describe_endpoint("vpce-12345")

        mock_client.describe_vpc_endpoints.assert_called_once_with(VpcEndpointIds=["vpce-12345"])
        assert result.success is True


class TestAWSExecutorVPCWaitForEndpointAvailable:
    """Test AWSExecutor.wait_for_endpoint_available method."""

    def test_wait_for_endpoint_available_exists(self):
        """AWSExecutor has wait_for_endpoint_available method."""
        from executors.aws_executor import AWSExecutor

        assert hasattr(AWSExecutor, "wait_for_endpoint_available")
        assert callable(AWSExecutor.wait_for_endpoint_available)

    def test_wait_for_endpoint_available_polls_until_available(self):
        """wait_for_endpoint_available polls until endpoint is available."""
        from executors.aws_executor import AWSExecutor

        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        # First call returns pending, second returns available
        mock_client.describe_vpc_endpoints.side_effect = [
            {"VpcEndpoints": [{"VpcEndpointId": "vpce-12345", "State": "pending"}]},
            {"VpcEndpoints": [{"VpcEndpointId": "vpce-12345", "State": "available"}]},
        ]

        executor = AWSExecutor(session=mock_session)
        result = executor.wait_for_endpoint_available("vpce-12345", timeout=60)

        assert result.success is True
        assert mock_client.describe_vpc_endpoints.call_count >= 1


class TestAWSExecutorRouteCreateRoute:
    """Test AWSExecutor.create_route method."""

    def test_create_route_exists(self):
        """AWSExecutor has create_route method."""
        from executors.aws_executor import AWSExecutor

        assert hasattr(AWSExecutor, "create_route")
        assert callable(AWSExecutor.create_route)

    def test_create_route_calls_ec2_create_route(self):
        """create_route calls EC2 CreateRoute API."""
        from executors.aws_executor import AWSExecutor

        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.create_route.return_value = {"Return": True}

        executor = AWSExecutor(session=mock_session)
        result = executor.create_route(
            route_table_id="rtb-12345",
            destination="0.0.0.0/0",
            endpoint_id="vpce-12345",
        )

        mock_client.create_route.assert_called_once_with(
            RouteTableId="rtb-12345",
            DestinationCidrBlock="0.0.0.0/0",
            VpcEndpointId="vpce-12345",
        )
        assert result.success is True


class TestAWSExecutorRouteDeleteRoute:
    """Test AWSExecutor.delete_route method."""

    def test_delete_route_exists(self):
        """AWSExecutor has delete_route method."""
        from executors.aws_executor import AWSExecutor

        assert hasattr(AWSExecutor, "delete_route")
        assert callable(AWSExecutor.delete_route)

    def test_delete_route_calls_ec2_delete_route(self):
        """delete_route calls EC2 DeleteRoute API."""
        from executors.aws_executor import AWSExecutor

        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.delete_route.return_value = {}

        executor = AWSExecutor(session=mock_session)
        result = executor.delete_route(
            route_table_id="rtb-12345",
            destination="0.0.0.0/0",
        )

        mock_client.delete_route.assert_called_once_with(
            RouteTableId="rtb-12345",
            DestinationCidrBlock="0.0.0.0/0",
        )
        assert result.success is True
