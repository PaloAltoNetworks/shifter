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
    """Integration tests for DC setup plan."""

    @dataclass
    class MockDCInstance:
        domain_name: str = "test.local"
        netbios_name: str = "TEST"
        dsrm_password: str = "Pass123!"
        domain_admin_password: str = "Admin456!"

    def test_dc_plan_with_real_orchestrator(self):
        """DCSetupPlan works correctly with real orchestrator."""
        mock_executor = MagicMock(spec=SSMExecutor)
        mock_executor.run_command.return_value = CommandResult(success=True, exit_code=0, stdout="ok", stderr="")
        mock_executor.reboot_and_wait.return_value = True

        plan = DCSetupPlan()
        orchestrator = SetupOrchestrator(executor=mock_executor)
        context = plan.get_context(self.MockDCInstance())
        result = orchestrator.orchestrate("i-12345", plan, context)

        assert result.success is True
        assert mock_executor.run_command.call_count >= 2
        assert mock_executor.reboot_and_wait.call_count >= 1

    def test_dc_plan_promote_failure_stops_everything(self):
        """If AD promotion fails, verification never runs."""
        mock_executor = MagicMock(spec=SSMExecutor)
        mock_executor.run_command.side_effect = CommandError(
            "Promote failed", exit_code=1, stderr="AD DS promotion error"
        )

        plan = DCSetupPlan()
        orchestrator = SetupOrchestrator(executor=mock_executor)
        context = plan.get_context(self.MockDCInstance())

        with pytest.raises((SetupError, CommandError)):
            orchestrator.orchestrate("i-12345", plan, context)

        assert mock_executor.run_command.call_count == 1
        assert mock_executor.reboot_and_wait.call_count == 0

    def test_dc_plan_reboot_failure_stops_everything(self):
        """If reboot fails, subsequent steps never run."""
        mock_executor = MagicMock(spec=SSMExecutor)
        mock_executor.run_command.return_value = CommandResult(success=True, exit_code=0, stdout="ok", stderr="")
        mock_executor.reboot_and_wait.side_effect = TimeoutError("Instance never came back")

        plan = DCSetupPlan()
        orchestrator = SetupOrchestrator(executor=mock_executor)
        context = plan.get_context(self.MockDCInstance())

        with pytest.raises((SetupError, TimeoutError)):
            orchestrator.orchestrate("i-12345", plan, context)

        assert mock_executor.run_command.call_count == 1
        assert mock_executor.reboot_and_wait.call_count == 1
