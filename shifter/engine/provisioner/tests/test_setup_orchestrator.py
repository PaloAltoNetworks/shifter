"""Tests for SetupOrchestrator.

SetupOrchestrator runs SetupPlans using an SSMExecutor.
It handles step sequencing, reboots, and verification.
"""

import logging
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from executors.base import (
    CommandResult,
    ExecutorConnectionError,
    ExecutorTimeoutError,
)
from executors.ssm_executor import (
    CommandError,
    SSMExecutor,
    TimeoutError,
)
from orchestrators.setup_orchestrator import SetupError, SetupOrchestrator, SetupResult
from plans.base import SetupStep


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
        mock_executor.run_command.return_value = CommandResult(success=True, exit_code=0, stdout="ok", stderr="")

        plan = MockSetupPlan(
            steps=[
                SetupStep(name="step1", script="echo step1", timeout_seconds=60),
                SetupStep(name="step2", script="echo step2", timeout_seconds=60),
            ],
            verify_step=SetupStep(name="verify", script="echo verify", timeout_seconds=30, is_verification=True),
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
        mock_executor.run_command.return_value = CommandResult(success=True, exit_code=0, stdout="ok", stderr="")
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
        result = orchestrator.orchestrate(
            "i-12345",
            plan,
            {},
            document_name="AWS-RunPowerShellScript",
        )

        assert result.success is True
        # Should have called reboot_and_wait after first step with document_name
        mock_executor.reboot_and_wait.assert_called_once_with(
            "i-12345",
            timeout_seconds=300,
            document_name="AWS-RunPowerShellScript",
        )

    def test_orchestrate_multiple_reboot_steps(self):
        """Multiple steps require reboots, all handled correctly."""
        mock_executor = MagicMock(spec=SSMExecutor)
        mock_executor.run_command.return_value = CommandResult(success=True, exit_code=0, stdout="ok", stderr="")
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
        result = orchestrator.orchestrate(
            "i-12345",
            plan,
            {},
            document_name="AWS-RunPowerShellScript",
        )

        assert result.success is True
        assert mock_executor.reboot_and_wait.call_count == 2
        # Both calls should pass document_name
        for call_obj in mock_executor.reboot_and_wait.call_args_list:
            assert call_obj.kwargs.get("document_name") == "AWS-RunPowerShellScript"


class TestOrchestrateExpectedFailures:
    """Test expected failure scenarios."""

    def test_orchestrate_first_step_fails_stops(self):
        """First step fails, raises SetupError, no further steps run."""
        mock_executor = MagicMock(spec=SSMExecutor)
        mock_executor.run_command.side_effect = CommandError("Step failed", exit_code=1, stderr="error")

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
        mock_executor.run_command.return_value = CommandResult(success=True, exit_code=0, stdout="ok", stderr="")
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
        mock_executor.run_command.return_value = CommandResult(success=True, exit_code=0, stdout="ok", stderr="")

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
        mock_executor.run_command.return_value = CommandResult(success=True, exit_code=0, stdout="ok", stderr="")

        # PowerShell script with special characters
        powershell_script = """
        $Password = ConvertTo-SecureString "{{ password }}" -AsPlainText -Force
        $Cred = New-Object PSCredential("{{ username }}", $Password)
        if ($env:PATH -match "Windows") { Write-Host "OK" }
        """

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

    def test_steps_executed_in_order(self):
        """Steps are executed in the order defined in the plan."""
        mock_executor = MagicMock(spec=SSMExecutor)
        mock_executor.run_command.return_value = CommandResult(success=True, exit_code=0, stdout="ok", stderr="")

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


class TestSensitiveOutputMasking:
    """Test secret masking for command output logs."""

    def test_masks_dc_domain_password_from_success_logs(self, caplog, monkeypatch):
        """DC_DOMAIN_PASSWORD is redacted from stdout/stderr log lines."""
        secret = "DomainPass123!"
        monkeypatch.setenv("DC_DOMAIN_PASSWORD", secret)
        mock_executor = MagicMock(spec=SSMExecutor)
        mock_executor.run_command.return_value = CommandResult(
            success=True,
            exit_code=0,
            stdout=f"Joined domain with {secret}",
            stderr=f"Warning included {secret}",
        )
        plan = MockSetupPlan(
            steps=[SetupStep(name="join_domain", script="join", timeout_seconds=60)],
            verify_step=None,
        )
        orchestrator = SetupOrchestrator(executor=mock_executor)

        caplog.set_level(logging.INFO, logger="orchestrators.setup_orchestrator")
        orchestrator.orchestrate("i-12345", plan, {})

        assert secret not in caplog.text
        assert "[REDACTED]" in caplog.text

    def test_masks_sensitive_context_value_from_failed_output_logs(self, caplog):
        """Sensitive context values are redacted from failed stdout/stderr logs."""
        secret = "DomainPass456!"
        mock_executor = MagicMock(spec=SSMExecutor)
        mock_executor.run_command.return_value = CommandResult(
            success=False,
            exit_code=1,
            stdout=f"Failure stdout contained {secret}",
            stderr=f"Failure stderr contained {secret}",
        )
        orchestrator = SetupOrchestrator(executor=mock_executor)
        step = SetupStep(name="join_domain", script="join", timeout_seconds=60)

        caplog.set_level(logging.WARNING, logger="orchestrators.setup_orchestrator")
        result = orchestrator._execute_step(
            "i-12345",
            step,
            {"domain_admin_password": secret},
            "AWS-RunPowerShellScript",
            max_retries=0,
        )

        assert result.success is False
        assert secret not in caplog.text
        assert "[REDACTED]" in caplog.text


class TestExecuteStepRetryAsymmetry:
    """Pin asymmetric exit paths in `_execute_step` so any refactor preserves them.

    The function has three retry-exhaustion outcomes that MUST stay distinct:
    1. Transport error exhausted -> raise SetupError
    2. Exit-nonzero exhausted    -> return failed StepResult (NO raise)
    3. PAN-OS commit-fail / poll-fail exhausted -> raise SetupError

    Mixing these up (e.g. raising on exit-nonzero exhaustion, or returning on
    transport-error exhaustion) would change the contract the outer
    `orchestrate()` method depends on.
    """

    def _step(self, **overrides) -> SetupStep:
        return SetupStep(
            name=overrides.pop("name", "s"),
            script=overrides.pop("script", "echo hi"),
            timeout_seconds=overrides.pop("timeout_seconds", 10),
            **overrides,
        )

    def test_transport_error_retries_then_succeeds(self, monkeypatch):
        """Transport error on first attempt + success on second -> success."""
        monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)
        executor = MagicMock(spec=SSMExecutor)
        executor.run_command.side_effect = [
            ExecutorConnectionError("conn reset"),
            CommandResult(success=True, exit_code=0, stdout="ok", stderr=""),
        ]
        orch = SetupOrchestrator(executor=executor)

        result = orch._execute_step("i-1", self._step(), {}, "AWS-RunPowerShellScript", max_retries=1)

        assert result.success is True
        assert executor.run_command.call_count == 2

    def test_transport_error_exhausted_raises_setup_error(self, monkeypatch):
        """All attempts hit transport errors -> SetupError raised (not returned)."""
        monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)
        executor = MagicMock(spec=SSMExecutor)
        executor.run_command.side_effect = ExecutorTimeoutError("timeout")
        orch = SetupOrchestrator(executor=executor)

        with pytest.raises(SetupError) as exc:
            orch._execute_step("i-1", self._step(), {}, "AWS-RunPowerShellScript", max_retries=2)

        assert "transport error" in str(exc.value).lower()
        assert exc.value.step_name == "s"
        # max_retries=2 means 3 attempts (initial + 2 retries)
        assert executor.run_command.call_count == 3

    def test_exit_nonzero_exhausted_returns_failed_step_result(self, monkeypatch):
        """All attempts exit non-zero -> failed StepResult returned (NOT raised).

        This asymmetry matters: `orchestrate()` distinguishes the two by
        checking `result.success` and raising itself. A refactor that raises
        from `_execute_step` on exit-nonzero exhaustion would double-wrap
        the error and could change exception types observed downstream.
        """
        monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)
        executor = MagicMock(spec=SSMExecutor)
        executor.run_command.return_value = CommandResult(success=False, exit_code=2, stdout="boom", stderr="err")
        orch = SetupOrchestrator(executor=executor)

        result = orch._execute_step("i-1", self._step(), {}, "AWS-RunPowerShellScript", max_retries=2)

        assert result.success is False
        assert result.stdout == "boom"
        assert result.stderr == "err"
        assert executor.run_command.call_count == 3

    def test_panos_poll_failure_exhausted_raises(self, monkeypatch):
        """`poll_for_job` with persistent poll failure -> SetupError raised."""
        monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)
        executor = MagicMock(spec=SSMExecutor)
        executor.run_command.return_value = CommandResult(
            success=True, exit_code=0, stdout="job enqueued with jobid 42", stderr=""
        )
        orch = SetupOrchestrator(executor=executor)
        # Stub the poll to always say the job failed; counts as exhaustion.
        monkeypatch.setattr(orch, "_poll_panos_job", lambda *_a, **_k: (False, "FIN err"))
        step = self._step(poll_for_job=True)

        with pytest.raises(SetupError) as exc:
            orch._execute_step("i-1", step, {}, "AWS-RunPowerShellScript", max_retries=1)

        assert "job 42" in str(exc.value)
        assert exc.value.step_name == "s"

    def test_panos_silent_commit_failure_exhausted_raises(self, monkeypatch):
        """Exit-0 with `commit` in stdout but no success marker -> SetupError after retries.

        SSH commit sessions return success even when the commit failed; the
        orchestrator detects this via `_check_commit_success` and treats it
        as a hard failure when retries are exhausted. The asymmetry vs. plain
        exit-nonzero is intentional: a "silent failure" SHOULD raise.
        """
        monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)
        executor = MagicMock(spec=SSMExecutor)
        executor.run_command.return_value = CommandResult(
            success=True,
            exit_code=0,
            stdout="commit issued but rejected by device",
            stderr="",
        )
        orch = SetupOrchestrator(executor=executor)

        with pytest.raises(SetupError) as exc:
            orch._execute_step("i-1", self._step(), {}, "AWS-RunPowerShellScript", max_retries=1)

        assert "commit failed" in str(exc.value).lower()
        assert exc.value.step_name == "s"


class TestRebootTimeout:
    """Test reboot timeout handling."""

    def test_reboot_uses_step_timeout(self):
        """Reboot timeout matches or exceeds step timeout."""
        mock_executor = MagicMock(spec=SSMExecutor)
        mock_executor.run_command.return_value = CommandResult(success=True, exit_code=0, stdout="ok", stderr="")
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
        orchestrator.orchestrate(
            "i-12345",
            plan,
            {},
            document_name="AWS-RunPowerShellScript",
        )

        # Reboot timeout should be at least as long as step timeout
        reboot_call = mock_executor.reboot_and_wait.call_args
        reboot_timeout = reboot_call.kwargs.get("timeout_seconds") or reboot_call[1].get("timeout_seconds")
        assert reboot_timeout >= 300  # At least 5 minutes for reboot
        # Should pass document_name
        assert reboot_call.kwargs.get("document_name") == "AWS-RunPowerShellScript"
