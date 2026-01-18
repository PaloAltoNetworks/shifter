"""AWS Executor for boto3 API calls.

AWSExecutor provides a consistent interface for AWS service interactions,
wrapping boto3 clients with error handling and result formatting.

This executor provides specific methods for NGFW lifecycle operations:
- EC2: start_instance, stop_instance, wait_for_running, wait_for_stopped, describe_instance
- VPC Endpoints: create_endpoint, delete_endpoint, describe_endpoint, wait_for_endpoint_available
- Route Table: create_route, delete_route
"""

import json
import logging
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError, WaiterError

from executors.base import CommandResult

logger = logging.getLogger(__name__)


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
        logger.debug(
            "__init__: session=%s region_name=%s",
            "provided" if session else "new",
            region_name,
        )
        if session is not None:
            self.session = session
        else:
            self.session = boto3.Session(region_name=region_name)

        # Cache for boto3 clients
        self._clients: dict[str, Any] = {}
        logger.info("__init__: AWSExecutor initialized region=%s", self.session.region_name)

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
        logger.debug("run_command: service=%s method=%s", service, method)
        try:
            client = self.get_client(service)
            method_fn = getattr(client, method)
            response = method_fn(**kwargs)

            logger.debug("run_command: success service=%s method=%s", service, method)
            return CommandResult(
                success=True,
                stdout=json.dumps(response, default=str),
                stderr="",
            )

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.warning(
                "run_command: ClientError service=%s method=%s code=%s",
                service,
                method,
                error_code,
            )
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )

        except Exception as e:
            logger.exception("run_command: unexpected error service=%s method=%s", service, method)
            return CommandResult(
                success=False,
                stdout="",
                stderr=str(e),
            )

    # =========================================================================
    # Action Dispatcher (for OpsOrchestrator integration)
    # =========================================================================

    def execute_action(self, action: str, context: dict[str, Any]) -> CommandResult:
        """Execute a named action using context parameters.

        This method provides the interface for OpsOrchestrator to dispatch
        operations to specific AWSExecutor methods based on the action name.

        Args:
            action: The action name (e.g., "start_instance", "stop_instance").
            context: Dict containing parameters for the action.

        Returns:
            CommandResult from the specific action method.

        Raises:
            ValueError: If the action is unknown.
        """
        logger.debug("execute_action: action=%s context_keys=%s", action, list(context.keys()))
        # Map action names to methods and their required context keys
        action_map = {
            # EC2 operations
            "start_instance": (self.start_instance, ["instance_id"]),
            "stop_instance": (self.stop_instance, ["instance_id"]),
            "wait_for_running": (self.wait_for_running, ["instance_id"]),
            "wait_for_stopped": (self.wait_for_stopped, ["instance_id"]),
            "describe_instance": (self.describe_instance, ["instance_id"]),
            # VPC endpoint operations
            "create_endpoint": (self.create_endpoint, ["vpc_id", "service_name", "subnet_ids"]),
            "delete_endpoint": (self.delete_endpoint, ["endpoint_id"]),
            "describe_endpoint": (self.describe_endpoint, ["endpoint_id"]),
            "wait_for_endpoint_available": (self.wait_for_endpoint_available, ["endpoint_id"]),
            # Route operations
            "create_route": (self.create_route, ["route_table_id", "destination", "endpoint_id"]),
            "delete_route": (self.delete_route, ["route_table_id", "destination"]),
        }

        if action not in action_map:
            logger.warning("execute_action: unknown action=%s", action)
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"Unknown action: {action}",
            )

        method, param_keys = action_map[action]

        # Extract parameters from context
        params = {}
        for key in param_keys:
            if key not in context:
                logger.warning(
                    "execute_action: missing param=%s for action=%s",
                    key,
                    action,
                )
                return CommandResult(
                    success=False,
                    stdout="",
                    stderr=f"Missing required parameter '{key}' for action '{action}'",
                )
            params[key] = context[key]

        logger.debug("execute_action: dispatching action=%s", action)
        return method(**params)

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
        logger.debug("start_instance: instance_id=%s", instance_id)
        try:
            client = self.get_client("ec2")
            response = client.start_instances(InstanceIds=[instance_id])
            logger.info("start_instance: started instance_id=%s", instance_id)
            return CommandResult(
                success=True,
                stdout=json.dumps(response, default=str),
                stderr="",
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.warning("start_instance: failed instance_id=%s code=%s", instance_id, error_code)
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            logger.exception("start_instance: unexpected error instance_id=%s", instance_id)
            return CommandResult(success=False, stdout="", stderr=str(e))

    def stop_instance(self, instance_id: str) -> CommandResult:
        """Stop an EC2 instance.

        Args:
            instance_id: The EC2 instance ID to stop.

        Returns:
            CommandResult with success status and response.
        """
        logger.debug("stop_instance: instance_id=%s", instance_id)
        try:
            client = self.get_client("ec2")
            response = client.stop_instances(InstanceIds=[instance_id])
            logger.info("stop_instance: stopped instance_id=%s", instance_id)
            return CommandResult(
                success=True,
                stdout=json.dumps(response, default=str),
                stderr="",
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.warning("stop_instance: failed instance_id=%s code=%s", instance_id, error_code)
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            logger.exception("stop_instance: unexpected error instance_id=%s", instance_id)
            return CommandResult(success=False, stdout="", stderr=str(e))

    def wait_for_running(self, instance_id: str, timeout: int = 300) -> CommandResult:
        """Wait for an EC2 instance to reach the 'running' state.

        Args:
            instance_id: The EC2 instance ID to wait for.
            timeout: Maximum time to wait in seconds (default 300).

        Returns:
            CommandResult with success status.
        """
        logger.debug("wait_for_running: instance_id=%s timeout=%d", instance_id, timeout)
        try:
            client = self.get_client("ec2")
            waiter = client.get_waiter("instance_running")
            # Convert timeout to waiter config (max attempts with 15s delay)
            max_attempts = max(1, timeout // 15)
            waiter.wait(
                InstanceIds=[instance_id],
                WaiterConfig={"Delay": 15, "MaxAttempts": max_attempts},
            )
            logger.info("wait_for_running: instance_id=%s is now running", instance_id)
            return CommandResult(
                success=True,
                stdout=f"Instance {instance_id} is now running",
                stderr="",
            )
        except WaiterError as e:
            logger.warning("wait_for_running: timeout instance_id=%s", instance_id)
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"Waiter timeout: {e!s}",
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.warning("wait_for_running: failed instance_id=%s code=%s", instance_id, error_code)
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            logger.exception("wait_for_running: unexpected error instance_id=%s", instance_id)
            return CommandResult(success=False, stdout="", stderr=str(e))

    def wait_for_stopped(self, instance_id: str, timeout: int = 300) -> CommandResult:
        """Wait for an EC2 instance to reach the 'stopped' state.

        Args:
            instance_id: The EC2 instance ID to wait for.
            timeout: Maximum time to wait in seconds (default 300).

        Returns:
            CommandResult with success status.
        """
        logger.debug("wait_for_stopped: instance_id=%s timeout=%d", instance_id, timeout)
        try:
            client = self.get_client("ec2")
            waiter = client.get_waiter("instance_stopped")
            max_attempts = max(1, timeout // 15)
            waiter.wait(
                InstanceIds=[instance_id],
                WaiterConfig={"Delay": 15, "MaxAttempts": max_attempts},
            )
            logger.info("wait_for_stopped: instance_id=%s is now stopped", instance_id)
            return CommandResult(
                success=True,
                stdout=f"Instance {instance_id} is now stopped",
                stderr="",
            )
        except WaiterError as e:
            logger.warning("wait_for_stopped: timeout instance_id=%s", instance_id)
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"Waiter timeout: {e!s}",
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.warning("wait_for_stopped: failed instance_id=%s code=%s", instance_id, error_code)
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            logger.exception("wait_for_stopped: unexpected error instance_id=%s", instance_id)
            return CommandResult(success=False, stdout="", stderr=str(e))

    def describe_instance(self, instance_id: str) -> CommandResult:
        """Describe an EC2 instance.

        Args:
            instance_id: The EC2 instance ID to describe.

        Returns:
            CommandResult with instance details in stdout.
        """
        logger.debug("describe_instance: instance_id=%s", instance_id)
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
            logger.warning("describe_instance: failed instance_id=%s code=%s", instance_id, error_code)
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            logger.exception("describe_instance: unexpected error instance_id=%s", instance_id)
            return CommandResult(success=False, stdout="", stderr=str(e))

    # =========================================================================
    # VPC Endpoint Operations (for cleanup of legacy GWLB endpoints)
    # =========================================================================

    def create_endpoint(
        self,
        vpc_id: str,
        service_name: str,
        subnet_ids: list[str],
    ) -> CommandResult:
        """Create a VPC endpoint.

        Args:
            vpc_id: The VPC ID where the endpoint will be created.
            service_name: The endpoint service name.
            subnet_ids: List of subnet IDs for the endpoint.

        Returns:
            CommandResult with endpoint details in stdout.
        """
        logger.debug("create_endpoint: vpc_id=%s service_name=%s", vpc_id, service_name)
        try:
            client = self.get_client("ec2")
            response = client.create_vpc_endpoint(
                VpcEndpointType="GatewayLoadBalancer",
                VpcId=vpc_id,
                ServiceName=service_name,
                SubnetIds=subnet_ids,
            )
            endpoint_id = response.get("VpcEndpoint", {}).get("VpcEndpointId", "unknown")
            logger.info("create_endpoint: created endpoint_id=%s", endpoint_id)
            return CommandResult(
                success=True,
                stdout=json.dumps(response, default=str),
                stderr="",
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.warning("create_endpoint: failed vpc_id=%s code=%s", vpc_id, error_code)
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            logger.exception("create_endpoint: unexpected error vpc_id=%s", vpc_id)
            return CommandResult(success=False, stdout="", stderr=str(e))

    def delete_endpoint(self, endpoint_id: str) -> CommandResult:
        """Delete a VPC endpoint.

        Args:
            endpoint_id: The VPC endpoint ID to delete.

        Returns:
            CommandResult with success status.
        """
        logger.debug("delete_endpoint: endpoint_id=%s", endpoint_id)
        try:
            client = self.get_client("ec2")
            response = client.delete_vpc_endpoints(VpcEndpointIds=[endpoint_id])
            # Check for unsuccessful deletions
            unsuccessful = response.get("Unsuccessful", [])
            if unsuccessful:
                logger.warning("delete_endpoint: failed endpoint_id=%s", endpoint_id)
                return CommandResult(
                    success=False,
                    stdout="",
                    stderr=f"Failed to delete endpoint: {unsuccessful}",
                )
            logger.info("delete_endpoint: deleted endpoint_id=%s", endpoint_id)
            return CommandResult(
                success=True,
                stdout=json.dumps(response, default=str),
                stderr="",
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.warning("delete_endpoint: failed endpoint_id=%s code=%s", endpoint_id, error_code)
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            logger.exception("delete_endpoint: unexpected error endpoint_id=%s", endpoint_id)
            return CommandResult(success=False, stdout="", stderr=str(e))

    def describe_endpoint(self, endpoint_id: str) -> CommandResult:
        """Describe a VPC endpoint.

        Args:
            endpoint_id: The VPC endpoint ID to describe.

        Returns:
            CommandResult with endpoint details in stdout.
        """
        logger.debug("describe_endpoint: endpoint_id=%s", endpoint_id)
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
            logger.warning("describe_endpoint: failed endpoint_id=%s code=%s", endpoint_id, error_code)
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            logger.exception("describe_endpoint: unexpected error endpoint_id=%s", endpoint_id)
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
        logger.debug("wait_for_endpoint_available: endpoint_id=%s timeout=%d", endpoint_id, timeout)
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
                        logger.info("wait_for_endpoint_available: endpoint_id=%s is available", endpoint_id)
                        return CommandResult(
                            success=True,
                            stdout=f"Endpoint {endpoint_id} is now available",
                            stderr="",
                        )
                    elif state in ("failed", "deleted", "rejected"):
                        logger.warning(
                            "wait_for_endpoint_available: endpoint_id=%s terminal state=%s",
                            endpoint_id,
                            state,
                        )
                        return CommandResult(
                            success=False,
                            stdout="",
                            stderr=f"Endpoint reached terminal state: {state}",
                        )
                time.sleep(poll_interval)

            logger.warning("wait_for_endpoint_available: timeout endpoint_id=%s", endpoint_id)
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"Timeout waiting for endpoint {endpoint_id} to become available",
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.warning("wait_for_endpoint_available: failed endpoint_id=%s code=%s", endpoint_id, error_code)
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            logger.exception("wait_for_endpoint_available: unexpected error endpoint_id=%s", endpoint_id)
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
        logger.debug(
            "create_route: route_table_id=%s destination=%s endpoint_id=%s",
            route_table_id,
            destination,
            endpoint_id,
        )
        try:
            client = self.get_client("ec2")
            response = client.create_route(
                RouteTableId=route_table_id,
                DestinationCidrBlock=destination,
                VpcEndpointId=endpoint_id,
            )
            logger.info("create_route: created route destination=%s", destination)
            return CommandResult(
                success=True,
                stdout=json.dumps(response, default=str),
                stderr="",
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.warning("create_route: failed route_table_id=%s code=%s", route_table_id, error_code)
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            logger.exception("create_route: unexpected error route_table_id=%s", route_table_id)
            return CommandResult(success=False, stdout="", stderr=str(e))

    def delete_route(self, route_table_id: str, destination: str) -> CommandResult:
        """Delete a route from a route table.

        Args:
            route_table_id: The route table ID.
            destination: The destination CIDR block to remove.

        Returns:
            CommandResult with success status.
        """
        logger.debug("delete_route: route_table_id=%s destination=%s", route_table_id, destination)
        try:
            client = self.get_client("ec2")
            response = client.delete_route(
                RouteTableId=route_table_id,
                DestinationCidrBlock=destination,
            )
            logger.info("delete_route: deleted route destination=%s", destination)
            return CommandResult(
                success=True,
                stdout=json.dumps(response, default=str),
                stderr="",
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.warning("delete_route: failed route_table_id=%s code=%s", route_table_id, error_code)
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            logger.exception("delete_route: unexpected error route_table_id=%s", route_table_id)
            return CommandResult(success=False, stdout="", stderr=str(e))

    def describe_instances(self, instance_ids: list[str]) -> CommandResult:
        """Describe multiple EC2 instances.

        Args:
            instance_ids: List of instance IDs to describe.

        Returns:
            CommandResult with instance details in stdout as JSON.
        """
        logger.debug("describe_instances: count=%d", len(instance_ids) if instance_ids else 0)
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
            logger.warning("describe_instances: failed code=%s", error_code)
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            logger.exception("describe_instances: unexpected error")
            return CommandResult(success=False, stdout="", stderr=str(e))

    def describe_endpoints(self, service_name: str) -> CommandResult:
        """Describe VPC endpoints filtered by service name.

        Args:
            service_name: The VPC endpoint service name to filter by.

        Returns:
            CommandResult with endpoint details in stdout as JSON.
        """
        logger.debug("describe_endpoints: service_name=%s", service_name)
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
            logger.warning("describe_endpoints: failed service_name=%s code=%s", service_name, error_code)
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            logger.exception("describe_endpoints: unexpected error service_name=%s", service_name)
            return CommandResult(success=False, stdout="", stderr=str(e))
