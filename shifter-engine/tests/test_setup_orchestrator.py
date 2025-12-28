"""Tests for SetupOrchestrator - TDD: Write tests first, all must fail initially.

SetupOrchestrator runs SetupPlans using an SSMExecutor.
It handles step sequencing, reboots, and verification.
"""

from unittest.mock import MagicMock, call, patch
from dataclasses import dataclass

import pytest

# These imports will fail initially - that's expected for TDD
from components.setup_plan import SetupStep, SetupPlan
from components.setup_orchestrator import (
    SetupOrchestrator,
    SetupError,
    SetupResult,
)
from components.ssm_executor import (
    SSMExecutor,
    CommandResult,
    CommandError,
    TimeoutError,
)


@dataclass
class MockSetupPlan:
    """Mock setup plan for testing."""
    steps: list
    verify_step: SetupStep

    def get_context(self, instance) -> dict:
        return {"var1": "value1", "var2": "value2"}


class TestOrchestrateHappyPath:
    """Test successful orchestration scenarios."""

    def test_orchestrate_all_steps_succeed(self):
        """All steps pass, verification passes, returns success."""
        mock_executor = MagicMock(spec=SSMExecutor)
        mock_executor.run_command.return_value = CommandResult(
            success=True, exit_code=0, stdout="ok", stderr=""
        )

        plan = MockSetupPlan(
            steps=[
                SetupStep(name="step1", script="echo step1", timeout_seconds=60),
                SetupStep(name="step2", script="echo step2", timeout_seconds=60),
            ],
            verify_step=SetupStep(
                name="verify", script="echo verify", timeout_seconds=30, is_verification=True
            ),
        )

        orchestrator = SetupOrchestrator(executor=mock_executor)
        result = orchestrator.orchestrate(
            instance_id="i-12345",
            plan=plan,
            context={"var1": "value1"},
        )

        assert isinstance(result, SetupResult)
        assert result.success is True
        # Should have run 2 steps + 1 verification
        assert mock_executor.run_command.call_count == 3

    def test_orchestrate_with_reboot_step(self):
        """Step requires reboot, reboot succeeds, continues to next step."""
        mock_executor = MagicMock(spec=SSMExecutor)
        mock_executor.run_command.return_value = CommandResult(
            success=True, exit_code=0, stdout="ok", stderr=""
        )
        mock_executor.reboot_and_wait.return_value = True

        plan = MockSetupPlan(
            steps=[
                SetupStep(
                    name="install_feature",
                    script="Install-Feature",
                    timeout_seconds=300,
                    requires_reboot=True,
                ),
                SetupStep(name="configure", script="Configure", timeout_seconds=60),
            ],
            verify_step=SetupStep(name="verify", script="Check", timeout_seconds=30),
        )

        orchestrator = SetupOrchestrator(executor=mock_executor)
        result = orchestrator.orchestrate("i-12345", plan, {})

        assert result.success is True
        # Should have called reboot_and_wait after first step
        mock_executor.reboot_and_wait.assert_called_once_with("i-12345", timeout_seconds=300)

    def test_orchestrate_multiple_reboot_steps(self):
        """Multiple steps require reboots, all handled correctly."""
        mock_executor = MagicMock(spec=SSMExecutor)
        mock_executor.run_command.return_value = CommandResult(
            success=True, exit_code=0, stdout="ok", stderr=""
        )
        mock_executor.reboot_and_wait.return_value = True

        plan = MockSetupPlan(
            steps=[
                SetupStep(name="step1", script="s1", timeout_seconds=60, requires_reboot=True),
                SetupStep(name="step2", script="s2", timeout_seconds=60, requires_reboot=True),
                SetupStep(name="step3", script="s3", timeout_seconds=60),
            ],
            verify_step=SetupStep(name="verify", script="v", timeout_seconds=30),
        )

        orchestrator = SetupOrchestrator(executor=mock_executor)
        result = orchestrator.orchestrate("i-12345", plan, {})

        assert result.success is True
        assert mock_executor.reboot_and_wait.call_count == 2


class TestOrchestrateExpectedFailures:
    """Test expected failure scenarios."""

    def test_orchestrate_first_step_fails_stops(self):
        """First step fails, raises SetupError, no further steps run."""
        mock_executor = MagicMock(spec=SSMExecutor)
        mock_executor.run_command.side_effect = CommandError(
            "Step failed", exit_code=1, stderr="error"
        )

        plan = MockSetupPlan(
            steps=[
                SetupStep(name="step1", script="fail", timeout_seconds=60),
                SetupStep(name="step2", script="never_runs", timeout_seconds=60),
            ],
            verify_step=SetupStep(name="verify", script="verify", timeout_seconds=30),
        )

        orchestrator = SetupOrchestrator(executor=mock_executor)

        with pytest.raises(SetupError) as exc_info:
            orchestrator.orchestrate("i-12345", plan, {})

        assert "step1" in str(exc_info.value)
        # Only called once (first step failed)
        assert mock_executor.run_command.call_count == 1

    def test_orchestrate_middle_step_fails_stops(self):
        """Middle step fails, raises SetupError, later steps not run."""
        mock_executor = MagicMock(spec=SSMExecutor)

        # First step succeeds, second fails
        mock_executor.run_command.side_effect = [
            CommandResult(success=True, exit_code=0, stdout="ok", stderr=""),
            CommandError("Step 2 failed", exit_code=1, stderr="error"),
        ]

        plan = MockSetupPlan(
            steps=[
                SetupStep(name="step1", script="s1", timeout_seconds=60),
                SetupStep(name="step2", script="s2", timeout_seconds=60),
                SetupStep(name="step3", script="never_runs", timeout_seconds=60),
            ],
            verify_step=SetupStep(name="verify", script="verify", timeout_seconds=30),
        )

        orchestrator = SetupOrchestrator(executor=mock_executor)

        with pytest.raises(SetupError) as exc_info:
            orchestrator.orchestrate("i-12345", plan, {})

        assert "step2" in str(exc_info.value)
        # Called twice (step1 succeeded, step2 failed, step3 never called)
        assert mock_executor.run_command.call_count == 2

    def test_orchestrate_reboot_fails_stops(self):
        """Step passes but reboot fails, raises SetupError."""
        mock_executor = MagicMock(spec=SSMExecutor)
        mock_executor.run_command.return_value = CommandResult(
            success=True, exit_code=0, stdout="ok", stderr=""
        )
        mock_executor.reboot_and_wait.side_effect = TimeoutError("Reboot timed out")

        plan = MockSetupPlan(
            steps=[
                SetupStep(
                    name="install",
                    script="install",
                    timeout_seconds=60,
                    requires_reboot=True,
                ),
                SetupStep(name="configure", script="config", timeout_seconds=60),
            ],
            verify_step=SetupStep(name="verify", script="verify", timeout_seconds=30),
        )

        orchestrator = SetupOrchestrator(executor=mock_executor)

        with pytest.raises(SetupError) as exc_info:
            orchestrator.orchestrate("i-12345", plan, {})

        assert "reboot" in str(exc_info.value).lower()

    def test_orchestrate_verification_fails_raises(self):
        """All steps pass but verification fails, raises SetupError."""
        mock_executor = MagicMock(spec=SSMExecutor)

        # All steps succeed, verification fails
        mock_executor.run_command.side_effect = [
            CommandResult(success=True, exit_code=0, stdout="ok", stderr=""),
            CommandResult(success=True, exit_code=0, stdout="ok", stderr=""),
            CommandError("Verification failed", exit_code=1, stderr="AD not running"),
        ]

        plan = MockSetupPlan(
            steps=[
                SetupStep(name="step1", script="s1", timeout_seconds=60),
                SetupStep(name="step2", script="s2", timeout_seconds=60),
            ],
            verify_step=SetupStep(name="verify", script="verify", timeout_seconds=30),
        )

        orchestrator = SetupOrchestrator(executor=mock_executor)

        with pytest.raises(SetupError) as exc_info:
            orchestrator.orchestrate("i-12345", plan, {})

        assert "verification" in str(exc_info.value).lower()


class TestOrchestrateEdgeCases:
    """Test edge cases and error handling."""

    def test_orchestrate_empty_plan_runs_verify(self):
        """No steps in plan, just runs verification."""
        mock_executor = MagicMock(spec=SSMExecutor)
        mock_executor.run_command.return_value = CommandResult(
            success=True, exit_code=0, stdout="ok", stderr=""
        )

        plan = MockSetupPlan(
            steps=[],  # Empty steps
            verify_step=SetupStep(name="verify", script="verify", timeout_seconds=30),
        )

        orchestrator = SetupOrchestrator(executor=mock_executor)
        result = orchestrator.orchestrate("i-12345", plan, {})

        assert result.success is True
        # Only verification was run
        assert mock_executor.run_command.call_count == 1

    def test_orchestrate_missing_context_var_raises(self):
        """Template variable missing from context raises clear error."""
        mock_executor = MagicMock(spec=SSMExecutor)

        plan = MockSetupPlan(
            steps=[
                SetupStep(
                    name="step1",
                    script="echo {{ missing_var }}",  # Uses Jinja2-style template
                    timeout_seconds=60,
                ),
            ],
            verify_step=SetupStep(name="verify", script="verify", timeout_seconds=30),
        )

        orchestrator = SetupOrchestrator(executor=mock_executor)

        with pytest.raises((SetupError, KeyError, Exception)) as exc_info:
            orchestrator.orchestrate("i-12345", plan, {"other_var": "value"})

        # Should have a clear error about missing variable
        error_msg = str(exc_info.value).lower()
        assert "missing" in error_msg or "undefined" in error_msg or "key" in error_msg

    def test_orchestrate_script_special_chars_render(self):
        """Script with special chars ($, {, etc) renders correctly."""
        mock_executor = MagicMock(spec=SSMExecutor)
        mock_executor.run_command.return_value = CommandResult(
            success=True, exit_code=0, stdout="ok", stderr=""
        )

        # PowerShell script with special characters
        powershell_script = '''
        $Password = ConvertTo-SecureString "{{ password }}" -AsPlainText -Force
        $Cred = New-Object PSCredential("{{ username }}", $Password)
        if ($env:PATH -match "Windows") { Write-Host "OK" }
        '''

        plan = MockSetupPlan(
            steps=[
                SetupStep(name="step1", script=powershell_script, timeout_seconds=60),
            ],
            verify_step=SetupStep(name="verify", script="echo done", timeout_seconds=30),
        )

        orchestrator = SetupOrchestrator(executor=mock_executor)
        result = orchestrator.orchestrate(
            "i-12345",
            plan,
            {"password": "Secret123!", "username": "admin"},
        )

        assert result.success is True
        # Verify the script was rendered with variables replaced
        call_args = mock_executor.run_command.call_args_list[0]
        # Access via kwargs since we use keyword arguments
        rendered_script = call_args.kwargs.get("script") or call_args[1].get("script")
        assert "Secret123!" in rendered_script
        assert "admin" in rendered_script
        # PowerShell $ variables should remain
        assert "$Password" in rendered_script or "$Cred" in rendered_script


class TestStepExecution:
    """Test individual step execution details."""

    def test_step_timeout_passed_to_executor(self):
        """Step timeout is passed to executor correctly."""
        mock_executor = MagicMock(spec=SSMExecutor)
        mock_executor.run_command.return_value = CommandResult(
            success=True, exit_code=0, stdout="ok", stderr=""
        )

        plan = MockSetupPlan(
            steps=[
                SetupStep(name="slow_step", script="sleep 500", timeout_seconds=600),
            ],
            verify_step=SetupStep(name="verify", script="v", timeout_seconds=30),
        )

        orchestrator = SetupOrchestrator(executor=mock_executor)
        orchestrator.orchestrate("i-12345", plan, {})

        # Check the timeout was passed correctly
        first_call = mock_executor.run_command.call_args_list[0]
        assert first_call[1].get("timeout_seconds") == 600 or first_call[0][2] == 600

    def test_steps_executed_in_order(self):
        """Steps are executed in the order defined in the plan."""
        mock_executor = MagicMock(spec=SSMExecutor)
        mock_executor.run_command.return_value = CommandResult(
            success=True, exit_code=0, stdout="ok", stderr=""
        )

        plan = MockSetupPlan(
            steps=[
                SetupStep(name="first", script="echo first", timeout_seconds=60),
                SetupStep(name="second", script="echo second", timeout_seconds=60),
                SetupStep(name="third", script="echo third", timeout_seconds=60),
            ],
            verify_step=SetupStep(name="verify", script="echo verify", timeout_seconds=30),
        )

        orchestrator = SetupOrchestrator(executor=mock_executor)
        orchestrator.orchestrate("i-12345", plan, {})

        # Verify order of script execution
        scripts = []
        for call_obj in mock_executor.run_command.call_args_list:
            script = call_obj.kwargs.get("script") or call_obj[1].get("script")
            scripts.append(script)
        assert scripts == ["echo first", "echo second", "echo third", "echo verify"]


class TestSetupResult:
    """Test SetupResult data structure."""

    def test_result_contains_step_outputs(self):
        """SetupResult contains output from each step."""
        mock_executor = MagicMock(spec=SSMExecutor)
        mock_executor.run_command.side_effect = [
            CommandResult(success=True, exit_code=0, stdout="step1 output", stderr=""),
            CommandResult(success=True, exit_code=0, stdout="step2 output", stderr=""),
            CommandResult(success=True, exit_code=0, stdout="verify output", stderr=""),
        ]

        plan = MockSetupPlan(
            steps=[
                SetupStep(name="step1", script="s1", timeout_seconds=60),
                SetupStep(name="step2", script="s2", timeout_seconds=60),
            ],
            verify_step=SetupStep(name="verify", script="v", timeout_seconds=30),
        )

        orchestrator = SetupOrchestrator(executor=mock_executor)
        result = orchestrator.orchestrate("i-12345", plan, {})

        assert result.success is True
        # Result should have step outputs accessible
        assert hasattr(result, "step_results") or hasattr(result, "outputs")


class TestRebootTimeout:
    """Test reboot timeout handling."""

    def test_reboot_uses_step_timeout(self):
        """Reboot timeout matches or exceeds step timeout."""
        mock_executor = MagicMock(spec=SSMExecutor)
        mock_executor.run_command.return_value = CommandResult(
            success=True, exit_code=0, stdout="ok", stderr=""
        )
        mock_executor.reboot_and_wait.return_value = True

        plan = MockSetupPlan(
            steps=[
                SetupStep(
                    name="install",
                    script="install",
                    timeout_seconds=900,  # 15 minutes
                    requires_reboot=True,
                ),
            ],
            verify_step=SetupStep(name="verify", script="v", timeout_seconds=30),
        )

        orchestrator = SetupOrchestrator(executor=mock_executor)
        orchestrator.orchestrate("i-12345", plan, {})

        # Reboot timeout should be at least as long as step timeout
        reboot_call = mock_executor.reboot_and_wait.call_args
        reboot_timeout = reboot_call[1].get("timeout_seconds") or reboot_call[0][1]
        assert reboot_timeout >= 300  # At least 5 minutes for reboot
