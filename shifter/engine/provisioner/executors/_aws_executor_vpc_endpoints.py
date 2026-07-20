"""VPC endpoint operations mixin for AWSExecutor.

Internal module. Do not import directly; import AWSExecutor from
executors.aws_executor instead.
"""

import json
import logging
import time

from botocore.client import BaseClient
from botocore.exceptions import ClientError

from executors.base import CommandResult
from log_redact import safe_log_fingerprint, safe_log_value

logger = logging.getLogger(__name__)


class _AWSExecutorVPCEndpointMixin:
    """VPC endpoint operations for AWSExecutor.

    Relies on ``self.get_client(...)`` from the composing class.
    """

    def get_client(self, service: str) -> BaseClient:
        raise NotImplementedError

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
        logger.debug(
            "create_endpoint: vpc_id_fp=%s service_name=%s",
            safe_log_fingerprint(vpc_id),
            safe_log_value(service_name),
        )
        try:
            client = self.get_client("ec2")
            response = client.create_vpc_endpoint(
                VpcEndpointType="GatewayLoadBalancer",
                VpcId=vpc_id,
                ServiceName=service_name,
                SubnetIds=subnet_ids,
            )
            endpoint_id = response.get("VpcEndpoint", {}).get("VpcEndpointId", "unknown")
            logger.info("create_endpoint: created endpoint_id_fp=%s", safe_log_fingerprint(endpoint_id))
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
                "create_endpoint: failed vpc_id_fp=%s code=%s",
                safe_log_fingerprint(vpc_id),
                safe_log_value(error_code),
            )
            return CommandResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            logger.exception("create_endpoint: unexpected error vpc_id_fp=%s", safe_log_fingerprint(vpc_id))
            return CommandResult(success=False, exit_code=-1, stdout="", stderr=str(e))

    def delete_endpoint(self, endpoint_id: str) -> CommandResult:
        """Delete a VPC endpoint.

        Args:
            endpoint_id: The VPC endpoint ID to delete.

        Returns:
            CommandResult with success status.
        """
        logger.debug("delete_endpoint: endpoint_id_fp=%s", safe_log_fingerprint(endpoint_id))
        success_result: CommandResult | None = None
        failure_stderr: str | None = None
        try:
            client = self.get_client("ec2")
            response = client.delete_vpc_endpoints(VpcEndpointIds=[endpoint_id])
            # Check for unsuccessful deletions
            unsuccessful = response.get("Unsuccessful", [])
            if unsuccessful:
                logger.warning("delete_endpoint: failed endpoint_id_fp=%s", safe_log_fingerprint(endpoint_id))
                failure_stderr = f"Failed to delete endpoint: {unsuccessful}"
            else:
                logger.info("delete_endpoint: deleted endpoint_id_fp=%s", safe_log_fingerprint(endpoint_id))
                success_result = CommandResult(
                    success=True,
                    exit_code=0,
                    stdout=json.dumps(response, default=str),
                    stderr="",
                )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.warning(
                "delete_endpoint: failed endpoint_id_fp=%s code=%s",
                safe_log_fingerprint(endpoint_id),
                safe_log_value(error_code),
            )
            failure_stderr = f"{error_code}: {error_message}"
        except Exception as e:
            logger.exception("delete_endpoint: unexpected error endpoint_id_fp=%s", safe_log_fingerprint(endpoint_id))
            failure_stderr = str(e)
        if success_result is not None:
            return success_result
        return CommandResult(success=False, exit_code=-1, stdout="", stderr=failure_stderr or "unknown error")

    def describe_endpoint(self, endpoint_id: str) -> CommandResult:
        """Describe a VPC endpoint.

        Args:
            endpoint_id: The VPC endpoint ID to describe.

        Returns:
            CommandResult with endpoint details in stdout.
        """
        logger.debug("describe_endpoint: endpoint_id_fp=%s", safe_log_fingerprint(endpoint_id))
        try:
            client = self.get_client("ec2")
            response = client.describe_vpc_endpoints(VpcEndpointIds=[endpoint_id])
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
                "describe_endpoint: failed endpoint_id_fp=%s code=%s",
                safe_log_fingerprint(endpoint_id),
                safe_log_value(error_code),
            )
            return CommandResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            logger.exception("describe_endpoint: unexpected error endpoint_id_fp=%s", safe_log_fingerprint(endpoint_id))
            return CommandResult(success=False, exit_code=-1, stdout="", stderr=str(e))

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
        logger.debug(
            "wait_for_endpoint_available: endpoint_id_fp=%s timeout=%d",
            safe_log_fingerprint(endpoint_id),
            timeout,
        )
        try:
            return self._poll_endpoint_until_available(endpoint_id, timeout)
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.warning(
                "wait_for_endpoint_available: failed endpoint_id_fp=%s code=%s",
                safe_log_fingerprint(endpoint_id),
                safe_log_value(error_code),
            )
            return CommandResult(success=False, exit_code=-1, stdout="", stderr=f"{error_code}: {error_message}")
        except Exception as e:
            logger.exception(
                "wait_for_endpoint_available: unexpected error endpoint_id_fp=%s",
                safe_log_fingerprint(endpoint_id),
            )
            return CommandResult(success=False, exit_code=-1, stdout="", stderr=str(e))

    def _poll_endpoint_until_available(self, endpoint_id: str, timeout: int) -> CommandResult:
        """Poll a VPC endpoint until it is available, hits a terminal state, or times out."""
        client = self.get_client("ec2")
        start_time = time.time()
        poll_interval = 10  # seconds
        while time.time() - start_time < timeout:
            response = client.describe_vpc_endpoints(VpcEndpointIds=[endpoint_id])
            endpoints = response.get("VpcEndpoints", [])
            state = endpoints[0].get("State", "") if endpoints else ""
            if state == "available":
                logger.info(
                    "wait_for_endpoint_available: endpoint_id_fp=%s is available",
                    safe_log_fingerprint(endpoint_id),
                )
                return CommandResult(
                    success=True,
                    exit_code=0,
                    stdout=f"Endpoint {endpoint_id} is now available",
                    stderr="",
                )
            if state in ("failed", "deleted", "rejected"):
                logger.warning(
                    "wait_for_endpoint_available: endpoint_id_fp=%s terminal state=%s",
                    safe_log_fingerprint(endpoint_id),
                    safe_log_value(state),
                )
                return CommandResult(
                    success=False,
                    exit_code=-1,
                    stdout="",
                    stderr=f"Endpoint reached terminal state: {state}",
                )
            time.sleep(poll_interval)
        logger.warning(
            "wait_for_endpoint_available: timeout endpoint_id_fp=%s",
            safe_log_fingerprint(endpoint_id),
        )
        return CommandResult(
            success=False,
            exit_code=-1,
            stdout="",
            stderr=f"Timeout waiting for endpoint {endpoint_id} to become available",
        )

    def describe_endpoints(self, service_name: str) -> CommandResult:
        """Describe VPC endpoints filtered by service name.

        Args:
            service_name: The VPC endpoint service name to filter by.

        Returns:
            CommandResult with endpoint details in stdout as JSON.
        """
        logger.debug("describe_endpoints: service_name=%s", safe_log_value(service_name))
        try:
            client = self.get_client("ec2")
            response = client.describe_vpc_endpoints(Filters=[{"Name": "service-name", "Values": [service_name]}])
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
                "describe_endpoints: failed service_name=%s code=%s",
                safe_log_value(service_name),
                safe_log_value(error_code),
            )
            return CommandResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            logger.exception("describe_endpoints: unexpected error service_name=%s", safe_log_value(service_name))
            return CommandResult(success=False, exit_code=-1, stdout="", stderr=str(e))
