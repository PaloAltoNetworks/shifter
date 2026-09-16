"""Tests for OpsOrchestrator.

OpsOrchestrator handles runtime operations like starting/stopping instances.
It depends on the ActionExecutor port and dispatches every step through
``execute_action`` — there is no capability sniffing or command fallback.
"""

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from executors.base import ActionExecutor, CommandExecutor, CommandResult
from orchestrators.base import StepResult
from orchestrators.ops_orchestrator import OpsOrchestrator, OpsResult


@dataclass
class MockStep:
    """Mock step for testing (names an action only)."""

    name: str
    action: str


@dataclass
class MockOpsPlan:
    """Mock operations plan for testing."""

    steps: list[Any]
    name: str = "mock_ops_plan"

    def get_context(self, target: Any) -> dict[str, Any]:
        return {}


class RecordingActionExecutor:
    """Spec-true ActionExecutor fake that records dispatched actions.

    Concrete class rather than an unconstrained ``MagicMock`` so a missing or
    wrong ``execute_action`` surface fails the test instead of being invented.
    """

    def __init__(self, results: list[CommandResult]) -> None:
        self._results = list(results)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute_action(self, action: str, context: dict[str, Any]) -> CommandResult:
        self.calls.append((action, context))
        return self._results.pop(0)


def _ok(stdout: str = "ok") -> CommandResult:
    return CommandResult(success=True, exit_code=0, stdout=stdout, stderr="")


def _fail(stderr: str = "boom") -> CommandResult:
    return CommandResult(success=False, exit_code=-1, stdout="", stderr=stderr)


class TestOpsOrchestratorOrchestrate:
    """Tests for OpsOrchestrator.orchestrate method."""

    def test_orchestrate_returns_result(self):
        """orchestrate returns OpsResult for an empty plan."""
        orchestrator = OpsOrchestrator(executor=RecordingActionExecutor([]))
        result = orchestrator.orchestrate("target-id", MockOpsPlan(steps=[]), {})

        assert isinstance(result, OpsResult)
        assert result.success is True

    def test_orchestrate_executes_plan_steps(self):
        """orchestrate executes each step and returns results."""
        executor = RecordingActionExecutor([_ok("output"), _ok("output")])
        plan = MockOpsPlan(
            steps=[
                MockStep(name="step1", action="start_instance"),
                MockStep(name="step2", action="wait_for_running"),
            ]
        )

        result = OpsOrchestrator(executor=executor).orchestrate("target-id", plan, {})

        assert len(result.step_results) == 2
        assert all(isinstance(r, StepResult) for r in result.step_results)

    def test_orchestrate_stops_on_failure(self):
        """orchestrate stops execution on first failure."""
        executor = RecordingActionExecutor([_ok(), _fail("Failed")])
        plan = MockOpsPlan(
            steps=[
                MockStep(name="step1", action="start"),
                MockStep(name="step2", action="fail"),
                MockStep(name="step3", action="never_reached"),
            ]
        )

        result = OpsOrchestrator(executor=executor).orchestrate("target-id", plan, {})

        assert result.success is False
        assert len(result.step_results) == 2
        # The third step's action must never have been dispatched.
        assert [action for action, _ in executor.calls] == ["start", "fail"]

    def test_empty_plan_returns_success(self):
        """Empty plan returns success with no step results."""
        result = OpsOrchestrator(executor=RecordingActionExecutor([])).orchestrate(
            "target-id", MockOpsPlan(steps=[]), {}
        )

        assert result.success is True
        assert len(result.step_results) == 0


class TestOpsOrchestratorActionDispatch:
    """OpsOrchestrator dispatches through the ActionExecutor port only."""

    def test_dispatches_via_execute_action_with_context(self):
        """Each step is dispatched through execute_action(action, context)."""
        executor = RecordingActionExecutor([_ok()])
        plan = MockOpsPlan(steps=[MockStep(name="start", action="start_instance")])
        context = {"instance_id": "i-12345"}

        result = OpsOrchestrator(executor=executor).orchestrate("i-12345", plan, context)

        assert executor.calls == [("start_instance", context)]
        assert result.success is True

    def test_propagates_execute_action_failure(self):
        """A failed action result surfaces on the StepResult."""
        executor = RecordingActionExecutor([_fail("Instance not found")])
        plan = MockOpsPlan(steps=[MockStep(name="start", action="start_instance")])

        result = OpsOrchestrator(executor=executor).orchestrate("i-invalid", plan, {"instance_id": "i-invalid"})

        assert result.success is False
        assert result.step_results[0].stderr == "Instance not found"

    def test_command_only_executor_fails_fast(self):
        """An executor without execute_action fails fast (no dead fallback).

        Uses a spec-constrained command-port mock (run_command/wait_for_ready/
        reboot_and_wait but no execute_action) to prove the removed
        ``hasattr``/``run_command`` fallback is gone: dispatch now requires the
        declared action port rather than silently calling a bogus contract.
        """
        command_only = MagicMock(spec=CommandExecutor)
        assert not hasattr(command_only, "execute_action")

        plan = MockOpsPlan(steps=[MockStep(name="start", action="start_instance")])
        orchestrator = OpsOrchestrator(executor=command_only)

        with pytest.raises(AttributeError):
            orchestrator.orchestrate("i-12345", plan, {"instance_id": "i-12345"})


class TestOpsOrchestratorWithNGFWPlans:
    """Tests for OpsOrchestrator with real NGFW plans."""

    def test_executes_ngfw_start_plan(self):
        """OpsOrchestrator executes NGFWStartPlan steps via execute_action."""
        from plans.ngfw_start import NGFWStartPlan

        executor = RecordingActionExecutor([_ok(), _ok()])
        result = OpsOrchestrator(executor=executor).orchestrate("i-12345", NGFWStartPlan(), {"instance_id": "i-12345"})

        actions = [action for action, _ in executor.calls]
        assert actions == ["start_instance", "wait_for_running"]
        assert result.success is True

    def test_executes_ngfw_stop_plan(self):
        """OpsOrchestrator executes NGFWStopPlan steps via execute_action."""
        from plans.ngfw_stop import NGFWStopPlan

        executor = RecordingActionExecutor([_ok(), _ok()])
        result = OpsOrchestrator(executor=executor).orchestrate("i-12345", NGFWStopPlan(), {"instance_id": "i-12345"})

        actions = [action for action, _ in executor.calls]
        assert actions == ["stop_instance", "wait_for_stopped"]
        assert result.success is True


def test_recording_fake_is_a_valid_action_executor():
    """The test fake actually satisfies the ActionExecutor port."""
    assert isinstance(RecordingActionExecutor([]), ActionExecutor)
