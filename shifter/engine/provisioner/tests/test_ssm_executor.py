"""Tests for SSMExecutor - TDD: Write tests first, all must fail initially.

SSMExecutor is a generic command executor that uses AWS SSM Run Command.
It has no knowledge of what it's running - just executes scripts and returns results.
"""

from unittest.mock import MagicMock, patch

import pytest

# These imports will fail initially - that's expected for TDD
from executors.ssm_executor import (
    CommandError,
    CommandResult,
    InstanceNotFoundError,
    InstanceTerminatedError,
    SSMExecutor,
    SSMExecutorError,
    TimeoutError,
)


class TestRunCommandHappyPath:
    """Test successful command execution."""

    def test_run_command_success(self):
        """Command succeeds, returns result with stdout/stderr."""
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()
        mock_ssm.send_command.return_value = {"Command": {"CommandId": "cmd-123"}}
        mock_ssm.get_command_invocation.return_value = {
            "Status": "Success",
            "ResponseCode": 0,
            "StandardOutputContent": "Hello World",
            "StandardErrorContent": "",
        }

        executor = SSMExecutor(ssm_client=mock_ssm, ec2_client=mock_ec2)
        result = executor.run_command(
            instance_id="i-12345",
            script="echo 'Hello World'",
            timeout_seconds=60,
        )

        assert isinstance(result, CommandResult)
        assert result.success is True
        assert result.exit_code == 0
        assert result.stdout == "Hello World"
        assert result.stderr == ""

    def test_run_command_returns_stderr_on_success(self):
        """Command can succeed but still have stderr output."""
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()
        mock_ssm.send_command.return_value = {"Command": {"CommandId": "cmd-123"}}
        mock_ssm.get_command_invocation.return_value = {
            "Status": "Success",
            "ResponseCode": 0,
            "StandardOutputContent": "Done",
            "StandardErrorContent": "Warning: deprecated feature",
        }

        executor = SSMExecutor(ssm_client=mock_ssm, ec2_client=mock_ec2)
        result = executor.run_command("i-12345", "some-script", 60)

        assert result.success is True
        assert result.stderr == "Warning: deprecated feature"


class TestRunCommandExpectedFailures:
    """Test expected failure scenarios."""

    def test_run_command_nonzero_exit_raises(self):
        """Non-zero exit code raises CommandError."""
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()
        mock_ssm.send_command.return_value = {"Command": {"CommandId": "cmd-123"}}
        mock_ssm.get_command_invocation.return_value = {
            "Status": "Failed",
            "ResponseCode": 1,
            "StandardOutputContent": "",
            "StandardErrorContent": "Command failed",
        }

        executor = SSMExecutor(ssm_client=mock_ssm, ec2_client=mock_ec2)

        with pytest.raises(CommandError) as exc_info:
            executor.run_command("i-12345", "exit 1", 60)

        assert exc_info.value.exit_code == 1
        assert "Command failed" in str(exc_info.value)

    def test_run_command_timeout_raises(self):
        """Command exceeds timeout raises TimeoutError."""
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()
        mock_ssm.send_command.return_value = {"Command": {"CommandId": "cmd-123"}}
        # Always return InProgress to simulate timeout
        mock_ssm.get_command_invocation.return_value = {
            "Status": "InProgress",
        }

        executor = SSMExecutor(ssm_client=mock_ssm, ec2_client=mock_ec2)

        with pytest.raises(TimeoutError) as exc_info:
            # Very short timeout to trigger quickly in tests
            executor.run_command("i-12345", "sleep 1000", timeout_seconds=1)

        assert "timed out" in str(exc_info.value).lower()

    def test_run_command_cancelled_raises(self):
        """Command cancelled raises CommandError."""
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()
        mock_ssm.send_command.return_value = {"Command": {"CommandId": "cmd-123"}}
        mock_ssm.get_command_invocation.return_value = {
            "Status": "Cancelled",
            "ResponseCode": -1,
            "StandardOutputContent": "",
            "StandardErrorContent": "Cancelled by user",
        }

        executor = SSMExecutor(ssm_client=mock_ssm, ec2_client=mock_ec2)

        with pytest.raises(CommandError) as exc_info:
            executor.run_command("i-12345", "script", 60)

        assert "cancelled" in str(exc_info.value).lower()


class TestRunCommandEdgeCases:
    """Test edge cases and error handling."""

    def test_run_command_instance_not_found_raises(self):
        """Invalid instance ID raises InstanceNotFoundError."""
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()
        from botocore.exceptions import ClientError

        mock_ssm.send_command.side_effect = ClientError(
            {"Error": {"Code": "InvalidInstanceId", "Message": "Instance not found"}},
            "SendCommand",
        )

        executor = SSMExecutor(ssm_client=mock_ssm, ec2_client=mock_ec2)

        with pytest.raises(InstanceNotFoundError):
            executor.run_command("i-invalid", "script", 60)

    def test_run_command_instance_terminated_raises(self):
        """Instance terminated during command raises InstanceTerminatedError."""
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()
        mock_ssm.send_command.return_value = {"Command": {"CommandId": "cmd-123"}}
        # First call returns InProgress, second indicates termination
        mock_ssm.get_command_invocation.side_effect = [
            {"Status": "InProgress"},
            {
                "Status": "Failed",
                "ResponseCode": -1,
                "StandardErrorContent": "Instance i-12345 is not in a valid state",
            },
        ]

        executor = SSMExecutor(ssm_client=mock_ssm, ec2_client=mock_ec2)

        with pytest.raises((InstanceTerminatedError, CommandError)):
            executor.run_command("i-12345", "script", 60)

    def test_run_command_long_output_handled(self):
        """Very long output is handled gracefully (truncated if needed)."""
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()
        mock_ssm.send_command.return_value = {"Command": {"CommandId": "cmd-123"}}

        long_output = "x" * 100000  # 100KB of output
        mock_ssm.get_command_invocation.return_value = {
            "Status": "Success",
            "ResponseCode": 0,
            "StandardOutputContent": long_output,
            "StandardErrorContent": "",
        }

        executor = SSMExecutor(ssm_client=mock_ssm, ec2_client=mock_ec2)
        result = executor.run_command("i-12345", "script", 60)

        # Should handle without crashing, may truncate
        assert result.success is True
        assert len(result.stdout) > 0


class TestWaitForAgentHappyPath:
    """Test successful agent wait scenarios."""

    def test_wait_for_agent_success(self):
        """Agent online within timeout returns True."""
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()
        mock_ec2.describe_instance_status.return_value = {"InstanceStatuses": []}
        mock_ssm.describe_instance_information.return_value = {
            "InstanceInformationList": [{"InstanceId": "i-12345", "PingStatus": "Online"}]
        }

        executor = SSMExecutor(ssm_client=mock_ssm, ec2_client=mock_ec2)
        result = executor.wait_for_agent("i-12345", timeout_seconds=60)

        assert result is True

    def test_wait_for_agent_eventually_online(self):
        """Agent comes online after a few retries."""
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()
        mock_ec2.describe_instance_status.return_value = {"InstanceStatuses": []}
        # First two calls return empty (agent not registered), third returns online
        mock_ssm.describe_instance_information.side_effect = [
            {"InstanceInformationList": []},
            {"InstanceInformationList": []},
            {"InstanceInformationList": [{"InstanceId": "i-12345", "PingStatus": "Online"}]},
        ]

        executor = SSMExecutor(ssm_client=mock_ssm, ec2_client=mock_ec2)
        result = executor.wait_for_agent("i-12345", timeout_seconds=60)

        assert result is True
        assert mock_ssm.describe_instance_information.call_count == 3


class TestWaitForAgentExpectedFailures:
    """Test expected failure scenarios for agent wait."""

    def test_wait_for_agent_timeout_raises(self):
        """Agent never online raises TimeoutError."""
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()
        mock_ec2.describe_instance_status.return_value = {"InstanceStatuses": []}
        # Always return empty (agent never registers)
        mock_ssm.describe_instance_information.return_value = {"InstanceInformationList": []}

        executor = SSMExecutor(ssm_client=mock_ssm, ec2_client=mock_ec2)

        with pytest.raises(TimeoutError) as exc_info:
            executor.wait_for_agent("i-12345", timeout_seconds=1)

        assert "agent" in str(exc_info.value).lower()

    def test_wait_for_agent_instance_terminated_raises(self):
        """Instance terminated while waiting raises error."""
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()

        mock_ssm.describe_instance_information.return_value = {"InstanceInformationList": []}
        mock_ec2.describe_instance_status.return_value = {
            "InstanceStatuses": [{"InstanceId": "i-12345", "InstanceState": {"Name": "terminated"}}]
        }

        executor = SSMExecutor(ssm_client=mock_ssm, ec2_client=mock_ec2)

        with pytest.raises(InstanceTerminatedError):
            executor.wait_for_agent("i-12345", timeout_seconds=60)


class TestRebootAndWaitHappyPath:
    """Test successful reboot scenarios."""

    def test_reboot_and_wait_success(self):
        """Reboot waits for status checks, SSM agent, and readiness probe."""
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()

        # EC2 reboot succeeds
        mock_ec2.reboot_instances.return_value = {}

        # Instance goes through stopping -> running
        mock_ec2.describe_instance_status.side_effect = [
            # First call - instance is stopping
            {"InstanceStatuses": []},  # No status during reboot
            # Second call - instance is running with status ok
            {
                "InstanceStatuses": [
                    {
                        "InstanceId": "i-12345",
                        "InstanceState": {"Name": "running"},
                        "InstanceStatus": {"Status": "ok"},
                        "SystemStatus": {"Status": "ok"},
                    }
                ]
            },
            # Additional calls for wait_for_agent (returns empty instance statuses)
            {"InstanceStatuses": []},
        ]

        # SSM agent comes back online
        mock_ssm.describe_instance_information.side_effect = [
            {"InstanceInformationList": [{"InstanceId": "i-12345", "PingStatus": "Online"}]},
        ]

        # Readiness probe succeeds
        mock_ssm.send_command.return_value = {"Command": {"CommandId": "cmd-123"}}
        mock_ssm.get_command_invocation.return_value = {
            "Status": "Success",
            "ResponseCode": 0,
            "StandardOutputContent": "ready",
            "StandardErrorContent": "",
        }

        with patch("time.sleep"):  # Skip actual sleeping in tests
            executor = SSMExecutor(ssm_client=mock_ssm, ec2_client=mock_ec2, poll_interval_seconds=0)
            result = executor.reboot_and_wait(
                "i-12345",
                timeout_seconds=120,
                document_name="AWS-RunPowerShellScript",
            )

        assert result is True
        mock_ec2.reboot_instances.assert_called_once_with(InstanceIds=["i-12345"])
        # Verify readiness probe was called with correct document
        mock_ssm.send_command.assert_called()
        call_kwargs = mock_ssm.send_command.call_args[1]
        assert call_kwargs["DocumentName"] == "AWS-RunPowerShellScript"

    def test_reboot_and_wait_uses_default_document(self):
        """Reboot uses default document type for readiness probe."""
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()

        mock_ec2.reboot_instances.return_value = {}
        mock_ec2.describe_instance_status.return_value = {
            "InstanceStatuses": [
                {
                    "InstanceId": "i-12345",
                    "InstanceState": {"Name": "running"},
                    "InstanceStatus": {"Status": "ok"},
                    "SystemStatus": {"Status": "ok"},
                }
            ]
        }
        mock_ssm.describe_instance_information.return_value = {
            "InstanceInformationList": [{"InstanceId": "i-12345", "PingStatus": "Online"}]
        }
        mock_ssm.send_command.return_value = {"Command": {"CommandId": "cmd-123"}}
        mock_ssm.get_command_invocation.return_value = {
            "Status": "Success",
            "ResponseCode": 0,
            "StandardOutputContent": "ready",
            "StandardErrorContent": "",
        }

        with patch("time.sleep"):
            executor = SSMExecutor(ssm_client=mock_ssm, ec2_client=mock_ec2, poll_interval_seconds=0)
            # Don't pass document_name - use default
            result = executor.reboot_and_wait("i-12345", timeout_seconds=120)

        assert result is True
        # Should use default document type
        call_kwargs = mock_ssm.send_command.call_args[1]
        assert call_kwargs["DocumentName"] == "AWS-RunShellScript"


class TestRebootAndWaitExpectedFailures:
    """Test expected failure scenarios for reboot."""

    def test_reboot_instance_never_returns_raises(self):
        """Instance doesn't come back after reboot raises TimeoutError."""
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()

        mock_ec2.reboot_instances.return_value = {}
        # Instance never comes back to running state
        mock_ec2.describe_instance_status.return_value = {"InstanceStatuses": []}
        mock_ssm.describe_instance_information.return_value = {"InstanceInformationList": []}

        executor = SSMExecutor(ssm_client=mock_ssm, ec2_client=mock_ec2)

        with pytest.raises(TimeoutError) as exc_info:
            executor.reboot_and_wait("i-12345", timeout_seconds=1)

        assert "reboot" in str(exc_info.value).lower() or "timeout" in str(exc_info.value).lower()

    def test_reboot_instance_terminated_raises(self):
        """Instance terminated during reboot raises error."""
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()

        mock_ec2.reboot_instances.return_value = {}
        mock_ec2.describe_instance_status.return_value = {
            "InstanceStatuses": [{"InstanceId": "i-12345", "InstanceState": {"Name": "terminated"}}]
        }

        executor = SSMExecutor(ssm_client=mock_ssm, ec2_client=mock_ec2)

        with pytest.raises(InstanceTerminatedError):
            executor.reboot_and_wait("i-12345", timeout_seconds=60)


class TestSSMExecutorInitialization:
    """Test SSMExecutor initialization and configuration."""

    def test_creates_default_clients_if_not_provided(self):
        """Creates boto3 clients if not provided."""
        with patch("boto3.Session") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session
            mock_session.client.return_value = MagicMock()

            SSMExecutor(region="us-east-1")

            # Should have created ssm and ec2 clients
            assert mock_session.client.call_count >= 1

    def test_uses_provided_clients(self):
        """Uses provided clients instead of creating new ones."""
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()

        executor = SSMExecutor(ssm_client=mock_ssm, ec2_client=mock_ec2)

        # Should use provided clients, not create new ones
        assert executor._ssm_client is mock_ssm
        assert executor._ec2_client is mock_ec2


class TestPollingBehavior:
    """Test polling and retry behavior."""

    def test_run_command_polls_until_complete(self):
        """run_command polls get_command_invocation until status is terminal."""
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()
        mock_ssm.send_command.return_value = {"Command": {"CommandId": "cmd-123"}}

        # Return InProgress twice, then Success
        mock_ssm.get_command_invocation.side_effect = [
            {"Status": "InProgress"},
            {"Status": "InProgress"},
            {"Status": "Success", "ResponseCode": 0, "StandardOutputContent": "done", "StandardErrorContent": ""},
        ]

        with patch("time.sleep"):
            executor = SSMExecutor(ssm_client=mock_ssm, ec2_client=mock_ec2)
            result = executor.run_command("i-12345", "script", 60)

        assert result.success is True
        assert mock_ssm.get_command_invocation.call_count == 3

    def test_polling_respects_poll_interval(self):
        """Polling waits between checks (but we mock time for fast tests)."""
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()
        mock_ssm.send_command.return_value = {"Command": {"CommandId": "cmd-123"}}
        mock_ssm.get_command_invocation.side_effect = [
            {"Status": "InProgress"},
            {"Status": "Success", "ResponseCode": 0, "StandardOutputContent": "", "StandardErrorContent": ""},
        ]

        with patch("time.sleep") as mock_sleep:
            executor = SSMExecutor(ssm_client=mock_ssm, ec2_client=mock_ec2, poll_interval_seconds=5)
            executor.run_command("i-12345", "script", 60)

            # Should have slept at least once
            assert mock_sleep.call_count >= 1


class TestVerifyAgentReadyHappyPath:
    """Test successful agent readiness verification."""

    def test_verify_agent_ready_success_first_attempt(self):
        """Agent ready on first probe attempt."""
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()

        # Mock successful command execution
        mock_ssm.send_command.return_value = {"Command": {"CommandId": "cmd-123"}}
        mock_ssm.get_command_invocation.return_value = {
            "Status": "Success",
            "ResponseCode": 0,
            "StandardOutputContent": "ready",
            "StandardErrorContent": "",
        }

        executor = SSMExecutor(ssm_client=mock_ssm, ec2_client=mock_ec2)
        result = executor.verify_agent_ready("i-12345", document_name="AWS-RunPowerShellScript")

        assert result is True
        mock_ssm.send_command.assert_called_once()
        # Verify it used the correct document type
        call_kwargs = mock_ssm.send_command.call_args[1]
        assert call_kwargs["DocumentName"] == "AWS-RunPowerShellScript"

    def test_verify_agent_ready_success_after_retries(self):
        """Agent ready after initial IPC failures."""
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()

        # First two attempts fail with IPC error, third succeeds
        mock_ssm.send_command.return_value = {"Command": {"CommandId": "cmd-123"}}
        mock_ssm.get_command_invocation.side_effect = [
            {
                "Status": "Failed",
                "ResponseCode": 1,
                "StandardOutputContent": "ipc timeout",
                "StandardErrorContent": "",
            },
            {
                "Status": "Failed",
                "ResponseCode": 1,
                "StandardOutputContent": "ipc timeout",
                "StandardErrorContent": "",
            },
            {
                "Status": "Success",
                "ResponseCode": 0,
                "StandardOutputContent": "ready",
                "StandardErrorContent": "",
            },
        ]

        executor = SSMExecutor(ssm_client=mock_ssm, ec2_client=mock_ec2)

        with patch("time.sleep"):  # Don't actually sleep
            result = executor.verify_agent_ready("i-12345", max_attempts=3)

        assert result is True
        assert mock_ssm.send_command.call_count == 3

    def test_verify_agent_ready_uses_default_document(self):
        """Default document is AWS-RunShellScript."""
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()

        mock_ssm.send_command.return_value = {"Command": {"CommandId": "cmd-123"}}
        mock_ssm.get_command_invocation.return_value = {
            "Status": "Success",
            "ResponseCode": 0,
            "StandardOutputContent": "ready",
            "StandardErrorContent": "",
        }

        executor = SSMExecutor(ssm_client=mock_ssm, ec2_client=mock_ec2)
        executor.verify_agent_ready("i-12345")

        call_kwargs = mock_ssm.send_command.call_args[1]
        assert call_kwargs["DocumentName"] == "AWS-RunShellScript"


class TestVerifyAgentReadyExpectedFailures:
    """Test expected failure scenarios for agent readiness verification."""

    def test_verify_agent_ready_all_attempts_fail(self):
        """Raises SSMExecutorError after all attempts exhausted."""
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()

        # All attempts fail
        mock_ssm.send_command.return_value = {"Command": {"CommandId": "cmd-123"}}
        mock_ssm.get_command_invocation.return_value = {
            "Status": "Failed",
            "ResponseCode": 1,
            "StandardOutputContent": "ipc timeout",
            "StandardErrorContent": "",
        }

        executor = SSMExecutor(ssm_client=mock_ssm, ec2_client=mock_ec2)

        with patch("time.sleep"), pytest.raises(SSMExecutorError) as exc_info:
            executor.verify_agent_ready("i-12345", max_attempts=3)

        assert "not ready after 3 attempts" in str(exc_info.value)

    def test_verify_agent_ready_respects_retry_delay(self):
        """Sleeps between retry attempts."""
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()

        # Fail first two, succeed third
        mock_ssm.send_command.return_value = {"Command": {"CommandId": "cmd-123"}}
        mock_ssm.get_command_invocation.side_effect = [
            {
                "Status": "Failed",
                "ResponseCode": 1,
                "StandardOutputContent": "",
                "StandardErrorContent": "",
            },
            {
                "Status": "Failed",
                "ResponseCode": 1,
                "StandardOutputContent": "",
                "StandardErrorContent": "",
            },
            {
                "Status": "Success",
                "ResponseCode": 0,
                "StandardOutputContent": "ready",
                "StandardErrorContent": "",
            },
        ]

        executor = SSMExecutor(ssm_client=mock_ssm, ec2_client=mock_ec2)

        with patch("time.sleep") as mock_sleep:
            executor.verify_agent_ready("i-12345", max_attempts=3)

        # Should have slept twice (after first and second failures)
        assert mock_sleep.call_count == 2
        # Each sleep should be 10 seconds
        mock_sleep.assert_called_with(10)
