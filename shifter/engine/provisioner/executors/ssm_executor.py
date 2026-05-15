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
from typing import ClassVar

import boto3
from botocore.exceptions import ClientError

from executors.base import (
    CommandResult,
    ExecutorCommandError,
    ExecutorError,
    ExecutorTimeoutError,
)

# Logger for timing info - useful for tuning timeouts
logger = logging.getLogger(__name__)


# Backward-compatible aliases for shared exception types
SSMExecutorError = ExecutorError
CommandError = ExecutorCommandError
TimeoutError = ExecutorTimeoutError


class InstanceNotFoundError(SSMExecutorError):
    """Raised when the target instance doesn't exist."""


class InstanceTerminatedError(SSMExecutorError):
    """Raised when the instance is terminated."""


class SSMExecutor:
    """Generic SSM command executor.

    Executes scripts on EC2 instances via SSM Run Command.
    Has no knowledge of what it's running - just executes and returns results.
    """

    # Terminal statuses for SSM commands
    TERMINAL_STATUSES: ClassVar[set[str]] = {"Success", "Failed", "Cancelled", "TimedOut"}

    def __init__(
        self,
        ssm_client=None,
        ec2_client=None,
        poll_interval_seconds: int = 5,
        region: str | None = None,
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
        stdin_input: str | None = None,
    ) -> CommandResult:
        """Run a script on an EC2 instance via SSM Run Command.

        Args:
            instance_id: Target EC2 instance ID
            script: Script content to execute
            timeout_seconds: Maximum time to wait for completion
            document_name: SSM document to use (default: PowerShell)
            stdin_input: Ignored. For executor interface compatibility with SSHExecutor.

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
            logger.info(f"Sent SSM command {command_id} to {instance_id}")
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "InvalidInstanceId":
                raise InstanceNotFoundError(f"Instance {instance_id} not found") from e
            raise SSMExecutorError(f"Failed to send command: {e}") from e

        # Poll for completion
        start_time = time.time()
        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                raise TimeoutError(f"Command timed out after {timeout_seconds}s on {instance_id}")

            try:
                result = self._ssm_client.get_command_invocation(
                    CommandId=command_id,
                    InstanceId=instance_id,
                )
            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "")
                logger.warning(
                    f"get_command_invocation failed: {error_code} - {e} "
                    f"(command={command_id}, instance={instance_id}, elapsed={elapsed:.1f}s)"
                )
                time.sleep(self._poll_interval)
                continue

            status = result.get("Status", "")
            logger.info(f"Command {command_id} status: {status} (elapsed={elapsed:.1f}s)")

            if status in self.TERMINAL_STATUSES:
                return self._build_terminal_result(instance_id, result, start_time)

            time.sleep(self._poll_interval)

    @staticmethod
    def _truncate_output(text: str, max_output: int = 50000) -> str:
        """Cap a single SSM stream to `max_output` chars with a marker."""
        if len(text) <= max_output:
            return text
        return text[:max_output] + "\n... (truncated)"

    def _build_terminal_result(self, instance_id: str, result: dict, start_time: float) -> CommandResult:
        """Translate a terminal SSM invocation result into `CommandResult` or raise.

        Owns the status-branch dispatch (`Success` / `Cancelled` / `TimedOut` /
        `Failed`) so `run_command` stays under the per-function complexity ceiling.
        """
        status = result.get("Status", "")
        exit_code = result.get("ResponseCode", -1)
        stdout = self._truncate_output(result.get("StandardOutputContent", ""))
        stderr = self._truncate_output(result.get("StandardErrorContent", ""))

        if status == "Success":
            elapsed = time.time() - start_time
            logger.info(f"SSM command completed in {elapsed:.1f}s on {instance_id}")
            return CommandResult(
                success=True,
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
            )
        if status == "Cancelled":
            raise CommandError(
                f"Command was cancelled on {instance_id}",
                exit_code=exit_code,
                stderr=stderr,
            )
        if status == "TimedOut":
            raise TimeoutError(f"Command timed out on {instance_id} (SSM timeout)")

        # status == "Failed". Detect instance-termination, then combine streams
        # into a single error envelope. PowerShell Write-Host goes to stdout;
        # SSM often returns a generic error in stderr, so include both.
        if "not in a valid state" in stderr.lower():
            raise InstanceTerminatedError(f"Instance {instance_id} is not in a valid state")
        error_parts = []
        if stdout:
            error_parts.append(f"stdout={stdout[:2000]}")
        if stderr:
            error_parts.append(f"stderr={stderr[:500]}")
        error_details = " | ".join(error_parts) if error_parts else "no output"
        raise CommandError(
            f"Command failed on {instance_id}",
            exit_code=exit_code,
            stderr=error_details,
        )

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
                raise TimeoutError(f"SSM agent on {instance_id} did not come online within {timeout_seconds}s")

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
                            raise InstanceTerminatedError(f"Instance {instance_id} is terminated")
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

    def verify_agent_ready(
        self,
        instance_id: str,
        timeout_seconds: int = 60,
        max_attempts: int = 5,
        document_name: str = "AWS-RunShellScript",
    ) -> bool:
        """Verify SSM agent is truly ready to execute commands.

        PingStatus='Online' only means the agent responded to AWS heartbeat.
        This method sends a trivial command to verify the document worker
        IPC subsystem is fully initialized.

        Args:
            instance_id: Target EC2 instance ID
            timeout_seconds: Timeout for each probe attempt
            max_attempts: Number of probe attempts before giving up
            document_name: SSM document to use (match the subsequent command type)

        Returns:
            True if agent executed command successfully

        Raises:
            SSMExecutorError: If agent fails all probe attempts
        """
        probe_script = "echo ready"  # Minimal command (works in both bash and PowerShell)

        for attempt in range(1, max_attempts + 1):
            try:
                result = self.run_command(
                    instance_id=instance_id,
                    script=probe_script,
                    timeout_seconds=timeout_seconds,
                    document_name=document_name,
                )
                if result.exit_code == 0:
                    return True
            except (CommandError, TimeoutError, SSMExecutorError) as e:
                if attempt < max_attempts:
                    time.sleep(10)  # Wait before retry
                    continue
                raise SSMExecutorError(
                    f"SSM agent on {instance_id} not ready after {max_attempts} attempts: {e}"
                ) from e

        return False

    def wait_for_ready(
        self,
        target: str,
        timeout_seconds: int = 300,
        document_name: str = "AWS-RunShellScript",
    ) -> bool:
        """Wait for SSM to be online and able to execute the requested document type."""
        self.wait_for_agent(target, timeout_seconds=timeout_seconds)
        remaining = max(30, min(timeout_seconds, 60))
        return self.verify_agent_ready(
            target,
            timeout_seconds=remaining,
            max_attempts=6,
            document_name=document_name,
        )

    def reboot_and_wait(
        self,
        instance_id: str,
        timeout_seconds: int = 300,
        document_name: str = "AWS-RunShellScript",
    ) -> bool:
        """Reboot an instance and wait for it to come back online.

        Args:
            instance_id: Target EC2 instance ID
            timeout_seconds: Maximum time to wait for instance to come back
            document_name: SSM document to use for readiness probe

        Returns:
            True if instance is back online and ready to execute commands

        Raises:
            TimeoutError: If instance doesn't come back in time
            InstanceTerminatedError: If instance is terminated
            SSMExecutorError: If readiness probe fails
        """
        try:
            self._ec2_client.reboot_instances(InstanceIds=[instance_id])
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "InvalidInstanceID.NotFound":
                raise InstanceNotFoundError(f"Instance {instance_id} not found") from e
            raise SSMExecutorError(f"Failed to reboot instance: {e}") from e

        time.sleep(10)  # let reboot initiate before we start polling
        start_time = time.time()

        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                raise TimeoutError(
                    f"Instance {instance_id} did not come back online after reboot within {timeout_seconds}s"
                )

            finalized = self._maybe_finalize_reboot(instance_id, start_time, timeout_seconds, document_name)
            if finalized is not None:
                return finalized

            time.sleep(self._poll_interval)

    def _maybe_finalize_reboot(
        self,
        instance_id: str,
        start_time: float,
        timeout_seconds: int,
        document_name: str,
    ) -> bool | None:
        """One poll-iteration of `reboot_and_wait`.

        Returns:
            True/False if the reboot has reached a terminal outcome this
            iteration (instance is up and SSM-ready, or proven ready in the
            remaining time budget). None if the caller should continue polling.

        Raises:
            InstanceTerminatedError: if the instance was terminated mid-reboot.
        """
        try:
            response = self._ec2_client.describe_instance_status(
                InstanceIds=[instance_id],
                IncludeAllInstances=True,
            )
        except ClientError:
            return None  # Instance might be transitioning; retry.

        statuses = response.get("InstanceStatuses", [])
        if not statuses:
            return None

        instance_status = statuses[0]
        state = instance_status.get("InstanceState", {}).get("Name", "")
        if state == "terminated":
            raise InstanceTerminatedError(f"Instance {instance_id} was terminated during reboot")
        if state != "running":
            return None

        instance_check = instance_status.get("InstanceStatus", {}).get("Status", "")
        system_check = instance_status.get("SystemStatus", {}).get("Status", "")
        if instance_check != "ok" or system_check != "ok":
            return None

        remaining_time = timeout_seconds - (time.time() - start_time)
        if remaining_time <= 0:
            return True  # No time left for probe; declare ready optimistically.

        # PingStatus=Online doesn't mean document worker is ready; do both.
        self.wait_for_agent(instance_id, timeout_seconds=int(remaining_time))
        remaining_time = timeout_seconds - (time.time() - start_time)
        if remaining_time <= 0:
            return True
        return self.verify_agent_ready(
            instance_id,
            timeout_seconds=min(60, int(remaining_time)),
            max_attempts=6,
            document_name=document_name,
        )
