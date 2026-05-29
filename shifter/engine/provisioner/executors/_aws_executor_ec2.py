"""EC2 instance operations mixin for AWSExecutor.

Internal module. Do not import directly; import AWSExecutor from
executors.aws_executor instead.
"""

import json
import logging
from typing import Any

from botocore.exceptions import ClientError, WaiterError

from executors.base import CommandResult
from log_redact import safe_log_fingerprint, safe_log_value

logger = logging.getLogger(__name__)


class _AWSExecutorEC2Mixin:
    """EC2 instance operations for AWSExecutor.

    Relies on ``self.get_client(...)`` from the composing class.
    """

    def get_client(self, service: str) -> Any:  # pragma: no cover - provided by base
        raise NotImplementedError

    def start_instance(self, instance_id: str) -> CommandResult:
        """Start an EC2 instance.

        Args:
            instance_id: The EC2 instance ID to start.

        Returns:
            CommandResult with success status and response.
        """
        logger.debug("start_instance: instance_id_fp=%s", safe_log_fingerprint(instance_id))
        try:
            client = self.get_client("ec2")
            response = client.start_instances(InstanceIds=[instance_id])
            logger.info("start_instance: started instance_id_fp=%s", safe_log_fingerprint(instance_id))
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
                "start_instance: failed instance_id_fp=%s code=%s",
                safe_log_fingerprint(instance_id),
                safe_log_value(error_code),
            )
            return CommandResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            logger.exception("start_instance: unexpected error instance_id_fp=%s", safe_log_fingerprint(instance_id))
            return CommandResult(success=False, exit_code=-1, stdout="", stderr=str(e))

    def stop_instance(self, instance_id: str) -> CommandResult:
        """Stop an EC2 instance.

        Args:
            instance_id: The EC2 instance ID to stop.

        Returns:
            CommandResult with success status and response.
        """
        logger.debug("stop_instance: instance_id_fp=%s", safe_log_fingerprint(instance_id))
        try:
            client = self.get_client("ec2")
            response = client.stop_instances(InstanceIds=[instance_id])
            logger.info("stop_instance: stopped instance_id_fp=%s", safe_log_fingerprint(instance_id))
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
                "stop_instance: failed instance_id_fp=%s code=%s",
                safe_log_fingerprint(instance_id),
                safe_log_value(error_code),
            )
            return CommandResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            logger.exception("stop_instance: unexpected error instance_id_fp=%s", safe_log_fingerprint(instance_id))
            return CommandResult(success=False, exit_code=-1, stdout="", stderr=str(e))

    def wait_for_running(self, instance_id: str, timeout: int = 300) -> CommandResult:
        """Wait for an EC2 instance to reach the 'running' state.

        Args:
            instance_id: The EC2 instance ID to wait for.
            timeout: Maximum time to wait in seconds (default 300).

        Returns:
            CommandResult with success status.
        """
        logger.debug("wait_for_running: instance_id_fp=%s timeout=%d", safe_log_fingerprint(instance_id), timeout)
        success_result: CommandResult | None = None
        failure_stderr: str | None = None
        try:
            client = self.get_client("ec2")
            waiter = client.get_waiter("instance_running")
            # Convert timeout to waiter config (max attempts with 15s delay)
            max_attempts = max(1, timeout // 15)
            waiter.wait(
                InstanceIds=[instance_id],
                WaiterConfig={"Delay": 15, "MaxAttempts": max_attempts},
            )
            logger.info("wait_for_running: instance_id_fp=%s is now running", safe_log_fingerprint(instance_id))
            success_result = CommandResult(
                success=True,
                exit_code=0,
                stdout=f"Instance {instance_id} is now running",
                stderr="",
            )
        except WaiterError as e:
            logger.warning("wait_for_running: timeout instance_id_fp=%s", safe_log_fingerprint(instance_id))
            failure_stderr = f"Waiter timeout: {e!s}"
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.warning(
                "wait_for_running: failed instance_id_fp=%s code=%s",
                safe_log_fingerprint(instance_id),
                safe_log_value(error_code),
            )
            failure_stderr = f"{error_code}: {error_message}"
        except Exception as e:
            logger.exception("wait_for_running: unexpected error instance_id_fp=%s", safe_log_fingerprint(instance_id))
            failure_stderr = str(e)
        if success_result is not None:
            return success_result
        return CommandResult(success=False, exit_code=-1, stdout="", stderr=failure_stderr or "unknown error")

    def wait_for_stopped(self, instance_id: str, timeout: int = 900) -> CommandResult:
        """Wait for an EC2 instance to reach the 'stopped' state.

        Args:
            instance_id: The EC2 instance ID to wait for.
            timeout: Maximum time to wait in seconds (default 900 for NGFW graceful shutdown).

        Returns:
            CommandResult with success status.
        """
        logger.debug("wait_for_stopped: instance_id_fp=%s timeout=%d", safe_log_fingerprint(instance_id), timeout)
        success_result: CommandResult | None = None
        failure_stderr: str | None = None
        try:
            client = self.get_client("ec2")
            waiter = client.get_waiter("instance_stopped")
            max_attempts = max(1, timeout // 15)
            waiter.wait(
                InstanceIds=[instance_id],
                WaiterConfig={"Delay": 15, "MaxAttempts": max_attempts},
            )
            logger.info("wait_for_stopped: instance_id_fp=%s is now stopped", safe_log_fingerprint(instance_id))
            success_result = CommandResult(
                success=True,
                exit_code=0,
                stdout=f"Instance {instance_id} is now stopped",
                stderr="",
            )
        except WaiterError as e:
            logger.warning("wait_for_stopped: timeout instance_id_fp=%s", safe_log_fingerprint(instance_id))
            failure_stderr = f"Waiter timeout: {e!s}"
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.warning(
                "wait_for_stopped: failed instance_id_fp=%s code=%s",
                safe_log_fingerprint(instance_id),
                safe_log_value(error_code),
            )
            failure_stderr = f"{error_code}: {error_message}"
        except Exception as e:
            logger.exception("wait_for_stopped: unexpected error instance_id_fp=%s", safe_log_fingerprint(instance_id))
            failure_stderr = str(e)
        if success_result is not None:
            return success_result
        return CommandResult(success=False, exit_code=-1, stdout="", stderr=failure_stderr or "unknown error")

    def describe_instance(self, instance_id: str) -> CommandResult:
        """Describe an EC2 instance.

        Args:
            instance_id: The EC2 instance ID to describe.

        Returns:
            CommandResult with instance details in stdout.
        """
        logger.debug("describe_instance: instance_id_fp=%s", safe_log_fingerprint(instance_id))
        try:
            client = self.get_client("ec2")
            response = client.describe_instances(InstanceIds=[instance_id])
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
                "describe_instance: failed instance_id_fp=%s code=%s",
                safe_log_fingerprint(instance_id),
                safe_log_value(error_code),
            )
            return CommandResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr=f"{error_code}: {error_message}",
            )
        except Exception as e:
            logger.exception("describe_instance: unexpected error instance_id_fp=%s", safe_log_fingerprint(instance_id))
            return CommandResult(success=False, exit_code=-1, stdout="", stderr=str(e))

    def describe_instances(self, instance_ids: list[str]) -> CommandResult:
        """Describe multiple EC2 instances.

        Args:
            instance_ids: List of instance IDs to describe.

        Returns:
            CommandResult with instance details in stdout as JSON.
        """
        logger.debug("describe_instances: count=%d", len(instance_ids) if instance_ids else 0)
        success_result: CommandResult | None = None
        failure_stderr: str | None = None
        if not instance_ids:
            success_result = CommandResult(
                success=True,
                exit_code=0,
                stdout=json.dumps({"Reservations": []}),
                stderr="",
            )
        else:
            try:
                client = self.get_client("ec2")
                response = client.describe_instances(InstanceIds=instance_ids)
                success_result = CommandResult(
                    success=True,
                    exit_code=0,
                    stdout=json.dumps(response, default=str),
                    stderr="",
                )
            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "Unknown")
                error_message = e.response.get("Error", {}).get("Message", str(e))
                logger.warning("describe_instances: failed code=%s", safe_log_value(error_code))
                failure_stderr = f"{error_code}: {error_message}"
            except Exception as e:
                logger.exception("describe_instances: unexpected error")
                failure_stderr = str(e)
        if success_result is not None:
            return success_result
        return CommandResult(success=False, exit_code=-1, stdout="", stderr=failure_stderr or "unknown error")
