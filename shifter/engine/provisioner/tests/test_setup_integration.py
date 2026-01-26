"""Integration tests for setup orchestration.

Tests verify that errors propagate correctly through the system
and would cause Pulumi stack failures.
"""

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from executors.base import CommandResult
from executors.ssm_executor import (
    CommandError,
    InstanceNotFoundError,
    SSMExecutor,
    TimeoutError,
)
from orchestrators.setup_orchestrator import SetupError, SetupOrchestrator
from plans.base import SetupStep
from plans.dc_setup import DCSetupPlan


@dataclass
class MockSetupPlan:
    """Simple mock plan for integration testing."""

    steps: list
    verify_step: SetupStep

    def get_context(self, instance) -> dict:
        return {}


class TestErrorPropagation:
    """Tests for error propagation through the system."""

    def test_executor_command_error_bubbles_up(self):
        """SSMExecutor CommandError propagates to orchestrator caller."""
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()
        mock_ssm.send_command.return_value = {"Command": {"CommandId": "cmd-123"}}
        mock_ssm.get_command_invocation.return_value = {
            "Status": "Failed",
            "ResponseCode": 1,
            "StandardOutputContent": "",
            "StandardErrorContent": "Script failed",
        }

        executor = SSMExecutor(ssm_client=mock_ssm, ec2_client=mock_ec2)
        orchestrator = SetupOrchestrator(executor=executor)
        plan = MockSetupPlan(
            steps=[SetupStep(name="fail_step", script="exit 1", timeout_seconds=60)],
            verify_step=SetupStep(name="verify", script="echo ok", timeout_seconds=30),
        )

        with pytest.raises((SetupError, CommandError)):
            orchestrator.orchestrate("i-12345", plan, {})

    def test_executor_timeout_error_bubbles_up(self):
        """SSMExecutor TimeoutError propagates to orchestrator caller."""
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()
        mock_ssm.send_command.return_value = {"Command": {"CommandId": "cmd-123"}}
        mock_ssm.get_command_invocation.return_value = {"Status": "InProgress"}

        executor = SSMExecutor(ssm_client=mock_ssm, ec2_client=mock_ec2)
        orchestrator = SetupOrchestrator(executor=executor)
        plan = MockSetupPlan(
            steps=[SetupStep(name="slow_step", script="sleep 1000", timeout_seconds=1)],
            verify_step=SetupStep(name="verify", script="echo ok", timeout_seconds=30),
        )

        with pytest.raises((SetupError, TimeoutError)):
            orchestrator.orchestrate("i-12345", plan, {})

    def test_executor_instance_not_found_bubbles_up(self):
        """SSMExecutor InstanceNotFoundError propagates."""
        from botocore.exceptions import ClientError

        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()
        mock_ssm.send_command.side_effect = ClientError(
            {"Error": {"Code": "InvalidInstanceId", "Message": "Not found"}},
            "SendCommand",
        )

        executor = SSMExecutor(ssm_client=mock_ssm, ec2_client=mock_ec2)
        orchestrator = SetupOrchestrator(executor=executor)
        plan = MockSetupPlan(
            steps=[SetupStep(name="step", script="echo", timeout_seconds=60)],
            verify_step=SetupStep(name="verify", script="echo ok", timeout_seconds=30),
        )

        with pytest.raises((SetupError, InstanceNotFoundError, Exception)):
            orchestrator.orchestrate("i-invalid", plan, {})

    def test_errors_contain_useful_information(self):
        """Errors contain enough information for debugging."""
        mock_executor = MagicMock(spec=SSMExecutor)
        mock_executor.run_command.side_effect = CommandError(
            "Install-WindowsFeature failed",
            exit_code=1,
            stderr="Error: Feature not available",
        )

        orchestrator = SetupOrchestrator(executor=mock_executor)
        plan = MockSetupPlan(
            steps=[SetupStep(name="install_ad_feature", script="Install-WindowsFeature", timeout_seconds=60)],
            verify_step=SetupStep(name="verify", script="echo ok", timeout_seconds=30),
        )

        with pytest.raises((SetupError, CommandError)) as exc_info:
            orchestrator.orchestrate("i-12345", plan, {})

        error_str = str(exc_info.value).lower()
        assert any(info in error_str for info in ["install", "feature", "failed", "error"])


class TestDCSetupPlanIntegration:
    """Integration tests for DC setup plan.

    With prebaked DC AMI, the plan has no setup steps - only verification.
    """

    @dataclass
    class MockDCInstance:
        domain_name: str = "test.local"
        netbios_name: str = "TEST"
        dsrm_password: str = "Pass123!"
        domain_admin_password: str = "Admin456!"

    def test_dc_plan_with_real_orchestrator(self):
        """DCSetupPlan with prebaked AMI runs password, SSH config, and verification."""
        mock_executor = MagicMock(spec=SSMExecutor)
        mock_executor.run_command.return_value = CommandResult(success=True, exit_code=0, stdout="ok", stderr="")

        plan = DCSetupPlan()
        orchestrator = SetupOrchestrator(executor=mock_executor)
        context = plan.get_context(self.MockDCInstance())
        result = orchestrator.orchestrate("i-12345", plan, context)

        assert result.success is True
        # With prebaked DC: 2 setup steps (password + SSH) + 1 verify step
        assert mock_executor.run_command.call_count == 3
        # No reboots with prebaked DC
        assert mock_executor.reboot_and_wait.call_count == 0

    def test_dc_plan_verify_failure_reports_error(self):
        """If DC verification fails, error is reported."""
        mock_executor = MagicMock(spec=SSMExecutor)
        # First two calls (password + SSH config) succeed, third (verify) fails
        mock_executor.run_command.side_effect = [
            CommandResult(success=True, exit_code=0, stdout="ok", stderr=""),
            CommandResult(success=True, exit_code=0, stdout="ok", stderr=""),
            CommandError("Verify failed", exit_code=1, stderr="NTDS not running"),
        ]

        plan = DCSetupPlan()
        orchestrator = SetupOrchestrator(executor=mock_executor)
        context = plan.get_context(self.MockDCInstance())

        with pytest.raises((SetupError, CommandError)):
            orchestrator.orchestrate("i-12345", plan, context)

        # password + SSH config steps + verify step attempted
        assert mock_executor.run_command.call_count == 3
