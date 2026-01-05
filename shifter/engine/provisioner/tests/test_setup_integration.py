"""Integration tests for setup orchestration - TDD: Write tests first.

These tests verify that errors propagate correctly through the system
and would cause Pulumi stack failures.
"""

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

# These imports will fail initially - that's expected for TDD
from executors.ssm_executor import (
    CommandError,
    CommandResult,
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
    """Test that errors propagate correctly through the system."""

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
        # Always return InProgress to trigger timeout
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


class TestPulumiIntegration:
    """Test that errors would correctly fail a Pulumi stack."""

    def test_setup_error_is_exception(self):
        """SetupError is an exception that would fail Pulumi."""
        # SetupError should be an Exception subclass
        assert issubclass(SetupError, Exception)

    def test_orchestrator_error_would_fail_pulumi(self):
        """Orchestrator errors would cause Pulumi stack failure.

        In Pulumi, uncaught exceptions during resource creation cause
        the stack to fail and trigger rollback. This test verifies that
        our errors are proper exceptions that would propagate correctly.
        """
        mock_executor = MagicMock(spec=SSMExecutor)
        mock_executor.run_command.side_effect = CommandError("Script failed", exit_code=1, stderr="error")

        orchestrator = SetupOrchestrator(executor=mock_executor)
        plan = MockSetupPlan(
            steps=[SetupStep(name="step", script="fail", timeout_seconds=60)],
            verify_step=SetupStep(name="verify", script="echo ok", timeout_seconds=30),
        )

        # This exception would cause Pulumi to fail the stack
        with pytest.raises(Exception) as exc_info:
            orchestrator.orchestrate("i-12345", plan, {})

        # Verify it's a real exception that would propagate
        assert exc_info.value is not None

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
            steps=[
                SetupStep(
                    name="install_ad_feature",
                    script="Install-WindowsFeature",
                    timeout_seconds=60,
                )
            ],
            verify_step=SetupStep(name="verify", script="echo ok", timeout_seconds=30),
        )

        with pytest.raises((SetupError, CommandError)) as exc_info:
            orchestrator.orchestrate("i-12345", plan, {})

        error_str = str(exc_info.value)
        # Error should contain useful debugging info
        assert any(
            info in error_str.lower()
            for info in [
                "install",
                "feature",
                "failed",
                "error",
            ]
        )


class TestDCSetupPlanIntegration:
    """Integration tests specifically for DC setup plan."""

    def test_dc_plan_with_real_orchestrator(self):
        """DCSetupPlan works correctly with real orchestrator."""
        mock_executor = MagicMock(spec=SSMExecutor)
        mock_executor.run_command.return_value = CommandResult(success=True, exit_code=0, stdout="ok", stderr="")
        mock_executor.reboot_and_wait.return_value = True

        plan = DCSetupPlan()
        orchestrator = SetupOrchestrator(executor=mock_executor)

        @dataclass
        class MockInstance:
            domain_name: str = "test.local"
            netbios_name: str = "TEST"
            dsrm_password: str = "Pass123!"
            domain_admin_password: str = "Admin456!"

        context = plan.get_context(MockInstance())
        result = orchestrator.orchestrate("i-12345", plan, context)

        assert result.success is True
        # With prebaked AMI: promote + verify = 2 run_command calls
        assert mock_executor.run_command.call_count >= 2
        # Only promote step requires reboot (AD DS feature is prebaked)
        assert mock_executor.reboot_and_wait.call_count >= 1

    def test_dc_plan_promote_failure_stops_everything(self):
        """If AD promotion fails, verification never runs."""
        mock_executor = MagicMock(spec=SSMExecutor)
        mock_executor.run_command.side_effect = CommandError(
            "Promote failed", exit_code=1, stderr="AD DS promotion error"
        )

        plan = DCSetupPlan()
        orchestrator = SetupOrchestrator(executor=mock_executor)

        @dataclass
        class MockInstance:
            domain_name: str = "test.local"
            netbios_name: str = "TEST"
            dsrm_password: str = "Pass123!"
            domain_admin_password: str = "Admin456!"

        context = plan.get_context(MockInstance())

        with pytest.raises((SetupError, CommandError)):
            orchestrator.orchestrate("i-12345", plan, context)

        # Should only have called run_command once (for promote step)
        assert mock_executor.run_command.call_count == 1
        # Should never have called reboot (failed before reboot)
        assert mock_executor.reboot_and_wait.call_count == 0

    def test_dc_plan_reboot_failure_stops_everything(self):
        """If reboot after install fails, promotion never runs."""
        mock_executor = MagicMock(spec=SSMExecutor)
        mock_executor.run_command.return_value = CommandResult(success=True, exit_code=0, stdout="ok", stderr="")
        mock_executor.reboot_and_wait.side_effect = TimeoutError("Instance never came back")

        plan = DCSetupPlan()
        orchestrator = SetupOrchestrator(executor=mock_executor)

        @dataclass
        class MockInstance:
            domain_name: str = "test.local"
            netbios_name: str = "TEST"
            dsrm_password: str = "Pass123!"
            domain_admin_password: str = "Admin456!"
            hostname: str = "dc-1"
            private_ip: str = "10.0.0.1"

        context = plan.get_context(MockInstance())

        with pytest.raises((SetupError, TimeoutError)):
            orchestrator.orchestrate("i-12345", plan, context)

        # Should have called run_command once (install succeeded)
        assert mock_executor.run_command.call_count == 1
        # Should have tried to reboot once
        assert mock_executor.reboot_and_wait.call_count == 1


class TestConcurrencyConsiderations:
    """Test considerations for running multiple setups concurrently."""

    def test_executor_instances_are_independent(self):
        """Multiple executor instances don't interfere with each other."""
        mock_ssm1 = MagicMock()
        mock_ec2_1 = MagicMock()
        mock_ssm2 = MagicMock()
        mock_ec2_2 = MagicMock()

        executor1 = SSMExecutor(ssm_client=mock_ssm1, ec2_client=mock_ec2_1)
        executor2 = SSMExecutor(ssm_client=mock_ssm2, ec2_client=mock_ec2_2)

        # They should use their own clients
        assert executor1._ssm_client is not executor2._ssm_client

    def test_orchestrator_instances_are_independent(self):
        """Multiple orchestrator instances don't interfere."""
        mock_executor1 = MagicMock(spec=SSMExecutor)
        mock_executor2 = MagicMock(spec=SSMExecutor)

        orch1 = SetupOrchestrator(executor=mock_executor1)
        orch2 = SetupOrchestrator(executor=mock_executor2)

        # They should use their own executors
        assert orch1.executor is not orch2.executor
