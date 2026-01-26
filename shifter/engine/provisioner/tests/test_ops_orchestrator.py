"""Tests for OpsOrchestrator.

OpsOrchestrator handles runtime operations like starting/stopping instances.
"""

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

from orchestrators.base import StepResult
from orchestrators.ops_orchestrator import OpsOrchestrator, OpsResult


@dataclass
class MockStep:
    """Mock step for testing."""

    name: str
    action: str
    params: list


@dataclass
class MockOpsPlan:
    """Mock operations plan for testing."""

    steps: list[Any]
    name: str = "mock_ops_plan"

    def get_context(self, target: Any) -> dict[str, Any]:
        return {}


class TestOpsOrchestratorOrchestrate:
    """Tests for OpsOrchestrator.orchestrate method."""

    def test_orchestrate_returns_result(self):
        """orchestrate returns OpsResult."""
        mock_executor = MagicMock()
        mock_executor.run_command.return_value = MagicMock(success=True, stdout="ok", stderr="")

        orchestrator = OpsOrchestrator(executor=mock_executor)
        plan = MockOpsPlan(steps=[])
        result = orchestrator.orchestrate("target-id", plan, {})

        assert isinstance(result, OpsResult)
        assert result.success is True

    def test_orchestrate_executes_plan_steps(self):
        """orchestrate executes each step and returns results."""
        mock_executor = MagicMock()
        mock_executor.execute_action.return_value = MagicMock(success=True, stdout="output", stderr="")

        plan = MockOpsPlan(
            steps=[
                MockStep(name="step1", action="start_instance", params=[]),
                MockStep(name="step2", action="verify_running", params=[]),
            ]
        )

        orchestrator = OpsOrchestrator(executor=mock_executor)
        result = orchestrator.orchestrate("target-id", plan, {})

        assert len(result.step_results) == 2
        assert all(isinstance(r, StepResult) for r in result.step_results)

    def test_orchestrate_stops_on_failure(self):
        """orchestrate stops execution on first failure."""
        mock_executor = MagicMock()
        mock_executor.execute_action.side_effect = [
            MagicMock(success=True, stdout="ok", stderr=""),
            MagicMock(success=False, stdout="", stderr="Failed"),
        ]

        plan = MockOpsPlan(
            steps=[
                MockStep(name="step1", action="start", params=[]),
                MockStep(name="step2", action="fail", params=[]),
                MockStep(name="step3", action="never_reached", params=[]),
            ]
        )

        orchestrator = OpsOrchestrator(executor=mock_executor)
        result = orchestrator.orchestrate("target-id", plan, {})

        assert result.success is False
        assert len(result.step_results) == 2

    def test_empty_plan_returns_success(self):
        """Empty plan returns success with no step results."""
        mock_executor = MagicMock()
        orchestrator = OpsOrchestrator(executor=mock_executor)
        plan = MockOpsPlan(steps=[])

        result = orchestrator.orchestrate("target-id", plan, {})

        assert result.success is True
        assert len(result.step_results) == 0


class TestOpsOrchestratorAWSExecutorIntegration:
    """Tests for OpsOrchestrator with AWSExecutor."""

    def test_uses_execute_action(self):
        """OpsOrchestrator uses execute_action() with context."""
        mock_executor = MagicMock()
        mock_executor.execute_action.return_value = MagicMock(success=True, stdout="ok", stderr="")

        plan = MockOpsPlan(steps=[MockStep(name="start", action="start_instance", params=["instance_id"])])
        context = {"instance_id": "i-12345"}

        orchestrator = OpsOrchestrator(executor=mock_executor)
        result = orchestrator.orchestrate("i-12345", plan, context)

        mock_executor.execute_action.assert_called_once_with("start_instance", context)
        assert result.success is True

    def test_handles_execute_action_failure(self):
        """OpsOrchestrator handles execute_action() failures."""
        mock_executor = MagicMock()
        mock_executor.execute_action.return_value = MagicMock(success=False, stdout="", stderr="Instance not found")

        plan = MockOpsPlan(steps=[MockStep(name="start", action="start_instance", params=["instance_id"])])

        orchestrator = OpsOrchestrator(executor=mock_executor)
        result = orchestrator.orchestrate("i-invalid", plan, {"instance_id": "i-invalid"})

        assert result.success is False
        assert result.step_results[0].stderr == "Instance not found"


class TestOpsOrchestratorWithNGFWPlans:
    """Tests for OpsOrchestrator with real NGFW plans."""

    def test_executes_ngfw_start_plan(self):
        """OpsOrchestrator executes NGFWStartPlan steps."""
        from plans.ngfw_start import NGFWStartPlan

        mock_executor = MagicMock()
        mock_executor.execute_action.return_value = MagicMock(success=True, stdout="ok", stderr="")

        plan = NGFWStartPlan()
        orchestrator = OpsOrchestrator(executor=mock_executor)
        result = orchestrator.orchestrate("i-12345", plan, {"instance_id": "i-12345"})

        assert mock_executor.execute_action.call_count == 2
        actions = [call[0][0] for call in mock_executor.execute_action.call_args_list]
        assert "start_instance" in actions
        assert "wait_for_running" in actions
        assert result.success is True

    def test_executes_ngfw_stop_plan(self):
        """OpsOrchestrator executes NGFWStopPlan steps."""
        from plans.ngfw_stop import NGFWStopPlan

        mock_executor = MagicMock()
        mock_executor.execute_action.return_value = MagicMock(success=True, stdout="ok", stderr="")

        plan = NGFWStopPlan()
        orchestrator = OpsOrchestrator(executor=mock_executor)
        result = orchestrator.orchestrate("i-12345", plan, {"instance_id": "i-12345"})

        assert mock_executor.execute_action.call_count == 2
        actions = [call[0][0] for call in mock_executor.execute_action.call_args_list]
        assert "stop_instance" in actions
        assert "wait_for_stopped" in actions
        assert result.success is True
