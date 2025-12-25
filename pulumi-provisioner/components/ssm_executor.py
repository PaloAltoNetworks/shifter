"""Generic SSM command executor for running scripts on EC2 instances.

SSMExecutor uses AWS Systems Manager Run Command to execute scripts
on EC2 instances. It provides:
- Command execution with timeout handling
- Wait for SSM agent to come online
- Reboot instance and wait for it to come back

This is a generic executor - it has no knowledge of what it's running.
The setup logic is handled by SetupPlan implementations.
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional

import boto3
from botocore.exceptions import ClientError

# Logger for timing info - useful for tuning timeouts
logger = logging.getLogger(__name__)


# Custom exceptions for clear error handling
class SSMExecutorError(Exception):
    """Base exception for SSM executor errors."""
    pass


class CommandError(SSMExecutorError):
    """Raised when a command fails (non-zero exit code)."""

    def __init__(self, message: str, exit_code: int = -1, stderr: str = ""):
        self.exit_code = exit_code
        self.stderr = stderr
        super().__init__(f"{message} (exit_code={exit_code}, stderr={stderr})")


class TimeoutError(SSMExecutorError):
    """Raised when an operation times out."""
    pass


class InstanceNotFoundError(SSMExecutorError):
    """Raised when the target instance doesn't exist."""
    pass


class InstanceTerminatedError(SSMExecutorError):
    """Raised when the instance is terminated."""
    pass


@dataclass
class CommandResult:
    """Result of a command execution."""
    success: bool
    exit_code: int
    stdout: str
    stderr: str


class SSMExecutor:
    """Generic SSM command executor.

    Executes scripts on EC2 instances via SSM Run Command.
    Has no knowledge of what it's running - just executes and returns results.
    """

    # Terminal statuses for SSM commands
    TERMINAL_STATUSES = {"Success", "Failed", "Cancelled", "TimedOut"}

    def __init__(
        self,
        ssm_client=None,
        ec2_client=None,
        poll_interval_seconds: int = 5,
        region: Optional[str] = None,
    ):
        """Initialize SSM executor.

        Args:
            ssm_client: Boto3 SSM client (created if not provided)
            ec2_client: Boto3 EC2 client (created if not provided)
            poll_interval_seconds: How often to poll for command completion
            region: AWS region (uses default if not provided)
        """
        self._ssm_client = ssm_client
        self._ec2_client = ec2_client

        # Only create clients if not provided
        if self._ssm_client is None or self._ec2_client is None:
            session = boto3.Session(region_name=region) if region else boto3.Session()
            if self._ssm_client is None:
                self._ssm_client = session.client("ssm")
            if self._ec2_client is None:
                self._ec2_client = session.client("ec2")

        self._poll_interval = poll_interval_seconds

    def run_command(
        self,
        instance_id: str,
        script: str,
        timeout_seconds: int = 300,
        document_name: str = "AWS-RunPowerShellScript",
    ) -> CommandResult:
        """Run a script on an EC2 instance via SSM Run Command.

        Args:
            instance_id: Target EC2 instance ID
            script: Script content to execute
            timeout_seconds: Maximum time to wait for completion
            document_name: SSM document to use (default: PowerShell)

        Returns:
            CommandResult with success status, exit code, stdout, stderr

        Raises:
            CommandError: If the command fails (non-zero exit)
            TimeoutError: If the command doesn't complete in time
            InstanceNotFoundError: If the instance doesn't exist
            InstanceTerminatedError: If the instance is terminated
        """
        try:
            # Send the command
            response = self._ssm_client.send_command(
                InstanceIds=[instance_id],
                DocumentName=document_name,
                Parameters={"commands": [script]},
                TimeoutSeconds=min(timeout_seconds, 3600),  # SSM max is 1 hour
            )
            command_id = response["Command"]["CommandId"]
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "InvalidInstanceId":
                raise InstanceNotFoundError(f"Instance {instance_id} not found")
            raise SSMExecutorError(f"Failed to send command: {e}")

        # Poll for completion
        start_time = time.time()
        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                raise TimeoutError(
                    f"Command timed out after {timeout_seconds}s on {instance_id}"
                )

            try:
                result = self._ssm_client.get_command_invocation(
                    CommandId=command_id,
                    InstanceId=instance_id,
                )
            except ClientError as e:
                # Command may not be ready yet
                time.sleep(self._poll_interval)
                continue

            status = result.get("Status", "")

            if status in self.TERMINAL_STATUSES:
                exit_code = result.get("ResponseCode", -1)
                stdout = result.get("StandardOutputContent", "")
                stderr = result.get("StandardErrorContent", "")

                # Truncate very long outputs
                max_output = 50000
                if len(stdout) > max_output:
                    stdout = stdout[:max_output] + "\n... (truncated)"
                if len(stderr) > max_output:
                    stderr = stderr[:max_output] + "\n... (truncated)"

                if status == "Success":
                    elapsed = time.time() - start_time
                    logger.info(f"SSM command completed in {elapsed:.1f}s on {instance_id}")
                    return CommandResult(
                        success=True,
                        exit_code=exit_code,
                        stdout=stdout,
                        stderr=stderr,
                    )
                elif status == "Cancelled":
                    raise CommandError(
                        f"Command was cancelled on {instance_id}",
                        exit_code=exit_code,
                        stderr=stderr,
                    )
                elif status == "TimedOut":
                    raise TimeoutError(
                        f"Command timed out on {instance_id} (SSM timeout)"
                    )
                else:  # Failed
                    # Check if it's an instance termination
                    if "not in a valid state" in stderr.lower():
                        raise InstanceTerminatedError(
                            f"Instance {instance_id} is not in a valid state"
                        )
                    raise CommandError(
                        f"Command failed on {instance_id}",
                        exit_code=exit_code,
                        stderr=stderr,
                    )

            time.sleep(self._poll_interval)

    def wait_for_agent(
        self,
        instance_id: str,
        timeout_seconds: int = 300,
    ) -> bool:
        """Wait for SSM agent to come online on an instance.

        Args:
            instance_id: Target EC2 instance ID
            timeout_seconds: Maximum time to wait

        Returns:
            True if agent is online

        Raises:
            TimeoutError: If agent doesn't come online in time
            InstanceTerminatedError: If instance is terminated
        """
        start_time = time.time()

        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                raise TimeoutError(
                    f"SSM agent on {instance_id} did not come online "
                    f"within {timeout_seconds}s"
                )

            # Check instance state first
            if self._ec2_client:
                try:
                    ec2_response = self._ec2_client.describe_instance_status(
                        InstanceIds=[instance_id],
                        IncludeAllInstances=True,
                    )
                    statuses = ec2_response.get("InstanceStatuses", [])
                    if statuses:
                        state = statuses[0].get("InstanceState", {}).get("Name", "")
                        if state == "terminated":
                            raise InstanceTerminatedError(
                                f"Instance {instance_id} is terminated"
                            )
                except ClientError:
                    pass  # Instance might not exist yet

            # Check SSM agent status
            try:
                response = self._ssm_client.describe_instance_information(
                    Filters=[
                        {"Key": "InstanceIds", "Values": [instance_id]},
                    ]
                )
                instances = response.get("InstanceInformationList", [])
                if instances:
                    ping_status = instances[0].get("PingStatus", "")
                    if ping_status == "Online":
                        return True
            except ClientError:
                pass  # May fail if instance not registered yet

            time.sleep(self._poll_interval)

    def reboot_and_wait(
        self,
        instance_id: str,
        timeout_seconds: int = 300,
    ) -> bool:
        """Reboot an instance and wait for it to come back online.

        Args:
            instance_id: Target EC2 instance ID
            timeout_seconds: Maximum time to wait for instance to come back

        Returns:
            True if instance is back online

        Raises:
            TimeoutError: If instance doesn't come back in time
            InstanceTerminatedError: If instance is terminated
        """
        # Initiate reboot
        try:
            self._ec2_client.reboot_instances(InstanceIds=[instance_id])
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "InvalidInstanceID.NotFound":
                raise InstanceNotFoundError(f"Instance {instance_id} not found")
            raise SSMExecutorError(f"Failed to reboot instance: {e}")

        # Wait a moment for reboot to initiate
        time.sleep(10)

        start_time = time.time()

        # Wait for instance to be running with status checks passing
        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                raise TimeoutError(
                    f"Instance {instance_id} did not come back online "
                    f"after reboot within {timeout_seconds}s"
                )

            try:
                response = self._ec2_client.describe_instance_status(
                    InstanceIds=[instance_id],
                    IncludeAllInstances=True,
                )
                statuses = response.get("InstanceStatuses", [])

                if statuses:
                    instance_status = statuses[0]
                    state = instance_status.get("InstanceState", {}).get("Name", "")

                    if state == "terminated":
                        raise InstanceTerminatedError(
                            f"Instance {instance_id} was terminated during reboot"
                        )

                    if state == "running":
                        # Check status checks
                        instance_check = instance_status.get(
                            "InstanceStatus", {}
                        ).get("Status", "")
                        system_check = instance_status.get(
                            "SystemStatus", {}
                        ).get("Status", "")

                        if instance_check == "ok" and system_check == "ok":
                            # Now wait for SSM agent
                            remaining_time = timeout_seconds - elapsed
                            if remaining_time > 0:
                                return self.wait_for_agent(
                                    instance_id,
                                    timeout_seconds=int(remaining_time),
                                )
            except ClientError:
                pass  # Instance might be transitioning

            time.sleep(self._poll_interval)
