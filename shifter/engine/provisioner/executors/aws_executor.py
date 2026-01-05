"""AWS Executor for boto3 API calls.

AWSExecutor provides a consistent interface for AWS service interactions,
wrapping boto3 clients with error handling and result formatting.

This executor provides specific methods for NGFW lifecycle operations:
- EC2: start_instance, stop_instance, wait_for_running, wait_for_stopped, describe_instance
- GWLB: register_target, deregister_target
- VPC Endpoints: create_endpoint, delete_endpoint, describe_endpoint, wait_for_endpoint_available
- Route Table: create_route, delete_route
"""

import json
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError, WaiterError

from executors.base import CommandResult


class AWSExecutor:
    """Executor for AWS API calls via boto3.

    Wraps boto3 session and clients to provide a consistent interface
    for orchestrators to interact with AWS services.

    Attributes:
        session: The boto3 Session used for creating clients.
    """

    def __init__(
        self,
        session: boto3.Session | None = None,
        region_name: str | None = None,
    ):
        """Initialize AWSExecutor.

        Args:
            session: Optional boto3 Session. If not provided, creates a new one.
            region_name: Optional AWS region name for the session.
        """
        if session is not None:
            self.session = session
        else:
            self.session = boto3.Session(region_name=region_name)

        # Cache for boto3 clients
        self._clients: dict[str, Any] = {}

    def get_client(self, service: str) -> Any:
        """Get a boto3 client for the specified service.

        Clients are cached for reuse.

        Args:
            service: AWS service name (e.g., 'ec2', 's3', 'ssm').

        Returns:
            Boto3 client for the service.
        """
        if service not in self._clients:
            self._clients[service] = self.session.client(service)
        return self._clients[service]

    def run_command(
        self,
        service: str,
        method: str,
        **kwargs: Any,
    ) -> CommandResult:
        """Execute an AWS API call.

        Args:
            service: AWS service name (e.g., 'ec2', 's3').
            method: Service method name (e.g., 'describe_instances').
            **kwargs: Arguments to pass to the service method.

        Returns:
            CommandResult with:
            - success: True if call succeeded, False on error
            - stdout: JSON-serialized response on success
            - stderr: Error message on failure
        """
        try:
            client = self.get_client(service)
            method_fn = getattr(client, method)
            response = method_fn(**kwargs)

            return CommandResult(
                success=True,
                stdout=json.dumps(response, default=str),
                stderr="",
            )

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )

        except Exception as e:
            return CommandResult(
                success=False,
                stdout="",
                stderr=str(e),
            )

    # =========================================================================
    # EC2 Operations
    # =========================================================================

    def start_instance(self, instance_id: str) -> CommandResult:
        """Start an EC2 instance.

        Args:
            instance_id: The EC2 instance ID to start.

        Returns:
            CommandResult with success status and response.
        """
        try:
            client = self.get_client("ec2")
            response = client.start_instances(InstanceIds=[instance_id])
            return CommandResult(
                success=True,
                stdout=json.dumps(response, default=str),
                stderr="",
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            return CommandResult(success=False, stdout="", stderr=str(e))

    def stop_instance(self, instance_id: str) -> CommandResult:
        """Stop an EC2 instance.

        Args:
            instance_id: The EC2 instance ID to stop.

        Returns:
            CommandResult with success status and response.
        """
        try:
            client = self.get_client("ec2")
            response = client.stop_instances(InstanceIds=[instance_id])
            return CommandResult(
                success=True,
                stdout=json.dumps(response, default=str),
                stderr="",
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            return CommandResult(success=False, stdout="", stderr=str(e))

    def wait_for_running(self, instance_id: str, timeout: int = 300) -> CommandResult:
        """Wait for an EC2 instance to reach the 'running' state.

        Args:
            instance_id: The EC2 instance ID to wait for.
            timeout: Maximum time to wait in seconds (default 300).

        Returns:
            CommandResult with success status.
        """
        try:
            client = self.get_client("ec2")
            waiter = client.get_waiter("instance_running")
            # Convert timeout to waiter config (max attempts with 15s delay)
            max_attempts = max(1, timeout // 15)
            waiter.wait(
                InstanceIds=[instance_id],
                WaiterConfig={"Delay": 15, "MaxAttempts": max_attempts},
            )
            return CommandResult(
                success=True,
                stdout=f"Instance {instance_id} is now running",
                stderr="",
            )
        except WaiterError as e:
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"Waiter timeout: {e!s}",
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            return CommandResult(success=False, stdout="", stderr=str(e))

    def wait_for_stopped(self, instance_id: str, timeout: int = 300) -> CommandResult:
        """Wait for an EC2 instance to reach the 'stopped' state.

        Args:
            instance_id: The EC2 instance ID to wait for.
            timeout: Maximum time to wait in seconds (default 300).

        Returns:
            CommandResult with success status.
        """
        try:
            client = self.get_client("ec2")
            waiter = client.get_waiter("instance_stopped")
            max_attempts = max(1, timeout // 15)
            waiter.wait(
                InstanceIds=[instance_id],
                WaiterConfig={"Delay": 15, "MaxAttempts": max_attempts},
            )
            return CommandResult(
                success=True,
                stdout=f"Instance {instance_id} is now stopped",
                stderr="",
            )
        except WaiterError as e:
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"Waiter timeout: {e!s}",
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            return CommandResult(success=False, stdout="", stderr=str(e))

    def describe_instance(self, instance_id: str) -> CommandResult:
        """Describe an EC2 instance.

        Args:
            instance_id: The EC2 instance ID to describe.

        Returns:
            CommandResult with instance details in stdout.
        """
        try:
            client = self.get_client("ec2")
            response = client.describe_instances(InstanceIds=[instance_id])
            return CommandResult(
                success=True,
                stdout=json.dumps(response, default=str),
                stderr="",
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            return CommandResult(success=False, stdout="", stderr=str(e))

    # =========================================================================
    # GWLB Operations
    # =========================================================================

    def register_target(self, target_group_arn: str, target_id: str) -> CommandResult:
        """Register a target with a GWLB target group.

        Args:
            target_group_arn: The ARN of the target group.
            target_id: The target ID (ENI ID for GWLB).

        Returns:
            CommandResult with success status.
        """
        try:
            client = self.get_client("elbv2")
            response = client.register_targets(
                TargetGroupArn=target_group_arn,
                Targets=[{"Id": target_id}],
            )
            return CommandResult(
                success=True,
                stdout=json.dumps(response, default=str),
                stderr="",
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            return CommandResult(success=False, stdout="", stderr=str(e))

    def deregister_target(self, target_group_arn: str, target_id: str) -> CommandResult:
        """Deregister a target from a GWLB target group.

        Args:
            target_group_arn: The ARN of the target group.
            target_id: The target ID (ENI ID for GWLB).

        Returns:
            CommandResult with success status.
        """
        try:
            client = self.get_client("elbv2")
            response = client.deregister_targets(
                TargetGroupArn=target_group_arn,
                Targets=[{"Id": target_id}],
            )
            return CommandResult(
                success=True,
                stdout=json.dumps(response, default=str),
                stderr="",
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            return CommandResult(success=False, stdout="", stderr=str(e))

    def wait_for_target_healthy(
        self,
        target_group_arn: str,
        target_id: str,
        timeout: int = 300,
    ) -> CommandResult:
        """Wait for a target to become healthy in a target group.

        Args:
            target_group_arn: The ARN of the target group.
            target_id: The target ID (ENI ID for GWLB).
            timeout: Maximum time to wait in seconds (default 300).

        Returns:
            CommandResult with success status.
        """
        try:
            client = self.get_client("elbv2")
            start_time = time.time()
            poll_interval = 10  # seconds

            while time.time() - start_time < timeout:
                response = client.describe_target_health(
                    TargetGroupArn=target_group_arn,
                    Targets=[{"Id": target_id}],
                )
                health_descriptions = response.get("TargetHealthDescriptions", [])
                if health_descriptions:
                    state = health_descriptions[0].get("TargetHealth", {}).get("State", "")
                    if state == "healthy":
                        return CommandResult(
                            success=True,
                            stdout=f"Target {target_id} is now healthy",
                            stderr="",
                        )
                    elif state in ("draining", "unavailable"):
                        return CommandResult(
                            success=False,
                            stdout="",
                            stderr=f"Target reached terminal state: {state}",
                        )
                time.sleep(poll_interval)

            return CommandResult(
                success=False,
                stdout="",
                stderr=f"Timeout waiting for target {target_id} to become healthy",
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            return CommandResult(success=False, stdout="", stderr=str(e))

    # =========================================================================
    # VPC Endpoint Operations
    # =========================================================================

    def create_endpoint(
        self,
        vpc_id: str,
        service_name: str,
        subnet_ids: list[str],
    ) -> CommandResult:
        """Create a VPC endpoint for GWLB.

        Args:
            vpc_id: The VPC ID where the endpoint will be created.
            service_name: The GWLB endpoint service name.
            subnet_ids: List of subnet IDs for the endpoint.

        Returns:
            CommandResult with endpoint details in stdout.
        """
        try:
            client = self.get_client("ec2")
            response = client.create_vpc_endpoint(
                VpcEndpointType="GatewayLoadBalancer",
                VpcId=vpc_id,
                ServiceName=service_name,
                SubnetIds=subnet_ids,
            )
            return CommandResult(
                success=True,
                stdout=json.dumps(response, default=str),
                stderr="",
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            return CommandResult(success=False, stdout="", stderr=str(e))

    def delete_endpoint(self, endpoint_id: str) -> CommandResult:
        """Delete a VPC endpoint.

        Args:
            endpoint_id: The VPC endpoint ID to delete.

        Returns:
            CommandResult with success status.
        """
        try:
            client = self.get_client("ec2")
            response = client.delete_vpc_endpoints(VpcEndpointIds=[endpoint_id])
            # Check for unsuccessful deletions
            unsuccessful = response.get("Unsuccessful", [])
            if unsuccessful:
                return CommandResult(
                    success=False,
                    stdout="",
                    stderr=f"Failed to delete endpoint: {unsuccessful}",
                )
            return CommandResult(
                success=True,
                stdout=json.dumps(response, default=str),
                stderr="",
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            return CommandResult(success=False, stdout="", stderr=str(e))

    def describe_endpoint(self, endpoint_id: str) -> CommandResult:
        """Describe a VPC endpoint.

        Args:
            endpoint_id: The VPC endpoint ID to describe.

        Returns:
            CommandResult with endpoint details in stdout.
        """
        try:
            client = self.get_client("ec2")
            response = client.describe_vpc_endpoints(VpcEndpointIds=[endpoint_id])
            return CommandResult(
                success=True,
                stdout=json.dumps(response, default=str),
                stderr="",
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            return CommandResult(success=False, stdout="", stderr=str(e))

    def wait_for_endpoint_available(
        self,
        endpoint_id: str,
        timeout: int = 300,
    ) -> CommandResult:
        """Wait for a VPC endpoint to become available.

        Args:
            endpoint_id: The VPC endpoint ID to wait for.
            timeout: Maximum time to wait in seconds (default 300).

        Returns:
            CommandResult with success status.
        """
        try:
            client = self.get_client("ec2")
            start_time = time.time()
            poll_interval = 10  # seconds

            while time.time() - start_time < timeout:
                response = client.describe_vpc_endpoints(VpcEndpointIds=[endpoint_id])
                endpoints = response.get("VpcEndpoints", [])
                if endpoints:
                    state = endpoints[0].get("State", "")
                    if state == "available":
                        return CommandResult(
                            success=True,
                            stdout=f"Endpoint {endpoint_id} is now available",
                            stderr="",
                        )
                    elif state in ("failed", "deleted", "rejected"):
                        return CommandResult(
                            success=False,
                            stdout="",
                            stderr=f"Endpoint reached terminal state: {state}",
                        )
                time.sleep(poll_interval)

            return CommandResult(
                success=False,
                stdout="",
                stderr=f"Timeout waiting for endpoint {endpoint_id} to become available",
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            return CommandResult(success=False, stdout="", stderr=str(e))

    # =========================================================================
    # Route Table Operations
    # =========================================================================

    def create_route(
        self,
        route_table_id: str,
        destination: str,
        endpoint_id: str,
    ) -> CommandResult:
        """Create a route in a route table pointing to a VPC endpoint.

        Args:
            route_table_id: The route table ID.
            destination: The destination CIDR block (e.g., '0.0.0.0/0').
            endpoint_id: The VPC endpoint ID to route to.

        Returns:
            CommandResult with success status.
        """
        try:
            client = self.get_client("ec2")
            response = client.create_route(
                RouteTableId=route_table_id,
                DestinationCidrBlock=destination,
                VpcEndpointId=endpoint_id,
            )
            return CommandResult(
                success=True,
                stdout=json.dumps(response, default=str),
                stderr="",
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            return CommandResult(success=False, stdout="", stderr=str(e))

    def delete_route(self, route_table_id: str, destination: str) -> CommandResult:
        """Delete a route from a route table.

        Args:
            route_table_id: The route table ID.
            destination: The destination CIDR block to remove.

        Returns:
            CommandResult with success status.
        """
        try:
            client = self.get_client("ec2")
            response = client.delete_route(
                RouteTableId=route_table_id,
                DestinationCidrBlock=destination,
            )
            return CommandResult(
                success=True,
                stdout=json.dumps(response, default=str),
                stderr="",
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            return CommandResult(success=False, stdout="", stderr=str(e))

    def describe_instances(self, instance_ids: list) -> CommandResult:
        """Describe multiple EC2 instances.

        Args:
            instance_ids: List of instance IDs to describe.

        Returns:
            CommandResult with instance details in stdout as JSON.
        """
        if not instance_ids:
            return CommandResult(
                success=True,
                stdout=json.dumps({"Reservations": []}),
                stderr="",
            )

        try:
            client = self.get_client("ec2")
            response = client.describe_instances(InstanceIds=instance_ids)
            return CommandResult(
                success=True,
                stdout=json.dumps(response, default=str),
                stderr="",
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            return CommandResult(success=False, stdout="", stderr=str(e))

    def describe_endpoints(self, service_name: str) -> CommandResult:
        """Describe VPC endpoints filtered by service name.

        Args:
            service_name: The VPC endpoint service name to filter by.

        Returns:
            CommandResult with endpoint details in stdout as JSON.
        """
        try:
            client = self.get_client("ec2")
            response = client.describe_vpc_endpoints(Filters=[{"Name": "service-name", "Values": [service_name]}])
            return CommandResult(
                success=True,
                stdout=json.dumps(response, default=str),
                stderr="",
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            return CommandResult(success=False, stdout="", stderr=str(e))
