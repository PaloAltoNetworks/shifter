"""Route table operations mixin for AWSExecutor.

Internal module. Do not import directly; import AWSExecutor from
executors.aws_executor instead.
"""

import json
import logging

from botocore.client import BaseClient
from botocore.exceptions import ClientError

from executors.base import CommandResult
from log_redact import safe_log_fingerprint, safe_log_value

logger = logging.getLogger(__name__)


class _AWSExecutorRouteMixin:
    """Route table operations for AWSExecutor.

    Relies on ``self.get_client(...)`` from the composing class.
    """

    def get_client(self, service: str) -> BaseClient:
        raise NotImplementedError

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
            "create_route: route_table_id_fp=%s destination=%s endpoint_id_fp=%s",
            safe_log_fingerprint(route_table_id),
            safe_log_value(destination),
            safe_log_fingerprint(endpoint_id),
        )
        try:
            client = self.get_client("ec2")
            response = client.create_route(
                RouteTableId=route_table_id,
                DestinationCidrBlock=destination,
                VpcEndpointId=endpoint_id,
            )
            logger.info("create_route: created route destination=%s", safe_log_value(destination))
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
                "create_route: failed route_table_id_fp=%s code=%s",
                safe_log_fingerprint(route_table_id),
                safe_log_value(error_code),
            )
            return CommandResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            logger.exception(
                "create_route: unexpected error route_table_id_fp=%s",
                safe_log_fingerprint(route_table_id),
            )
            return CommandResult(success=False, exit_code=-1, stdout="", stderr=str(e))

    def delete_route(self, route_table_id: str, destination: str) -> CommandResult:
        """Delete a route from a route table.

        Args:
            route_table_id: The route table ID.
            destination: The destination CIDR block to remove.

        Returns:
            CommandResult with success status.
        """
        logger.debug(
            "delete_route: route_table_id_fp=%s destination=%s",
            safe_log_fingerprint(route_table_id),
            safe_log_value(destination),
        )
        try:
            client = self.get_client("ec2")
            response = client.delete_route(
                RouteTableId=route_table_id,
                DestinationCidrBlock=destination,
            )
            logger.info("delete_route: deleted route destination=%s", safe_log_value(destination))
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
                "delete_route: failed route_table_id_fp=%s code=%s",
                safe_log_fingerprint(route_table_id),
                safe_log_value(error_code),
            )
            return CommandResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            logger.exception(
                "delete_route: unexpected error route_table_id_fp=%s",
                safe_log_fingerprint(route_table_id),
            )
            return CommandResult(success=False, exit_code=-1, stdout="", stderr=str(e))
