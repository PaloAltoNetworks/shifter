"""AWS Executor for boto3 API calls.

AWSExecutor provides a consistent interface for AWS service interactions,
wrapping boto3 clients with error handling and result formatting.
"""

import json
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import ClientError

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
        session: Optional[boto3.Session] = None,
        region_name: Optional[str] = None,
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
        self._clients: Dict[str, Any] = {}

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
