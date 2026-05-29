"""AWS Executor for boto3 API calls.

AWSExecutor provides a consistent interface for AWS service interactions,
wrapping boto3 clients with error handling and result formatting.

This executor provides specific methods for NGFW lifecycle operations:
- EC2: start_instance, stop_instance, wait_for_running, wait_for_stopped, describe_instance
- VPC Endpoints: create_endpoint, delete_endpoint, describe_endpoint, wait_for_endpoint_available
- Route Table: create_route, delete_route

The per-surface methods live in private sibling mixins
(``_aws_executor_ec2``, ``_aws_executor_vpc_endpoints``,
``_aws_executor_routes``) that are composed here. Callers should continue to
import ``AWSExecutor`` from ``executors.aws_executor``.
"""

import json
import logging
from collections.abc import Callable
from typing import Any

import boto3
from botocore.exceptions import ClientError

from executors.base import CommandResult

from ._aws_executor_ec2 import _AWSExecutorEC2Mixin
from ._aws_executor_routes import _AWSExecutorRouteMixin
from ._aws_executor_vpc_endpoints import _AWSExecutorVPCEndpointMixin

logger = logging.getLogger(__name__)


class AWSExecutor(
    _AWSExecutorEC2Mixin,
    _AWSExecutorVPCEndpointMixin,
    _AWSExecutorRouteMixin,
):
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
    ) -> None:
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

    # NOSONAR S6542 - boto3.client() returns botocore.client.BaseClient whose
    # method surface varies by service name; static typing is intentionally Any
    # so callers can dispatch on service-specific methods (describe_instances,
    # describe_vpc_endpoints, etc.) without a per-service overload.
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
                exit_code=0,
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
                exit_code=-1,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )

        except Exception as e:
            logger.exception("run_command: unexpected error service=%s method=%s", service, method)
            return CommandResult(
                success=False,
                exit_code=-1,
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
        action_map: dict[str, tuple[Callable[..., CommandResult], list[str]]] = {
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
                exit_code=-1,
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
                    exit_code=-1,
                    stdout="",
                    stderr=f"Missing required parameter '{key}' for action '{action}'",
                )
            params[key] = context[key]

        logger.debug("execute_action: dispatching action=%s", action)
        return method(**params)
