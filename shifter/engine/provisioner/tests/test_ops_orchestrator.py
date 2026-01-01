"""Tests for OpsOrchestrator - TDD: Write tests first, all must fail initially.

OpsOrchestrator handles runtime operations like:
- Starting/stopping instances
- Managing routes
- Executing operational plans
"""

from dataclasses import dataclass
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest


@dataclass
class MockOpsPlan:
    """Mock operations plan for testing."""

    steps: List[Any]
    name: str = "mock_ops_plan"

    def get_context(self, target: Any) -> Dict[str, Any]:
        return {}


class TestOpsOrchestratorInit:
    """Test OpsOrchestrator initialization."""

    def test_init_stores_executor(self):
        """OpsOrchestrator stores the provided executor."""
        from orchestrators.ops_orchestrator import OpsOrchestrator

        mock_executor = MagicMock()
        orchestrator = OpsOrchestrator(executor=mock_executor)

        assert orchestrator.executor is mock_executor

    def test_init_requires_executor(self):
        """OpsOrchestrator requires an executor."""
        from orchestrators.ops_orchestrator import OpsOrchestrator
        import inspect

        sig = inspect.signature(OpsOrchestrator.__init__)
        params = sig.parameters

        # Should have executor parameter
        assert "executor" in params


class TestOpsOrchestratorOrchestrate:
    """Test OpsOrchestrator.orchestrate method."""

    def test_orchestrate_returns_result(self):
        """orchestrate returns a result object."""
        from orchestrators.ops_orchestrator import OpsOrchestrator, OpsResult

        mock_executor = MagicMock()
        mock_executor.run_command.return_value = MagicMock(success=True, stdout="ok", stderr="")

        orchestrator = OpsOrchestrator(executor=mock_executor)
        plan = MockOpsPlan(steps=[])

        result = orchestrator.orchestrate("target-id", plan, {})

        assert isinstance(result, OpsResult)
        assert result.success is True

    def test_orchestrate_executes_plan_steps(self):
        """orchestrate executes each step in the plan."""
        from orchestrators.ops_orchestrator import OpsOrchestrator
        from orchestrators.base import StepResult

        mock_executor = MagicMock()
        mock_executor.run_command.return_value = MagicMock(success=True, stdout="ok", stderr="")

        @dataclass
        class MockStep:
            name: str
            action: str
            params: dict

        plan = MockOpsPlan(
            steps=[
                MockStep(name="step1", action="start_instance", params={}),
                MockStep(name="step2", action="verify_running", params={}),
            ]
        )

        orchestrator = OpsOrchestrator(executor=mock_executor)
        result = orchestrator.orchestrate("target-id", plan, {})

        # Should have executed steps
        assert len(result.step_results) == 2

    def test_orchestrate_stops_on_failure(self):
        """orchestrate stops execution on first failure."""
        from orchestrators.ops_orchestrator import OpsOrchestrator

        mock_executor = MagicMock()
        # First call succeeds, second fails
        mock_executor.run_command.side_effect = [
            MagicMock(success=True, stdout="ok", stderr=""),
            MagicMock(success=False, stdout="", stderr="Failed"),
        ]

        @dataclass
        class MockStep:
            name: str
            action: str
            params: dict

        plan = MockOpsPlan(
            steps=[
                MockStep(name="step1", action="start", params={}),
                MockStep(name="step2", action="fail", params={}),
                MockStep(name="step3", action="never_reached", params={}),
            ]
        )

        orchestrator = OpsOrchestrator(executor=mock_executor)
        result = orchestrator.orchestrate("target-id", plan, {})

        # Should have stopped after step2 failure
        assert result.success is False
        assert len(result.step_results) == 2

    def test_orchestrate_returns_step_results(self):
        """orchestrate returns results for each executed step."""
        from orchestrators.ops_orchestrator import OpsOrchestrator
        from orchestrators.base import StepResult

        mock_executor = MagicMock()
        mock_executor.run_command.return_value = MagicMock(success=True, stdout="output", stderr="")

        @dataclass
        class MockStep:
            name: str
            action: str
            params: dict

        plan = MockOpsPlan(
            steps=[MockStep(name="test_step", action="test", params={})]
        )

        orchestrator = OpsOrchestrator(executor=mock_executor)
        result = orchestrator.orchestrate("target-id", plan, {})

        assert len(result.step_results) == 1
        step_result = result.step_results[0]
        assert isinstance(step_result, StepResult)
        assert step_result.step_name == "test_step"
        assert step_result.success is True


class TestOpsOrchestratorProtocolCompliance:
    """Test that OpsOrchestrator implements the Orchestrator protocol."""

    def test_has_orchestrate_method(self):
        """OpsOrchestrator has orchestrate method."""
        from orchestrators.ops_orchestrator import OpsOrchestrator

        assert hasattr(OpsOrchestrator, "orchestrate")
        assert callable(getattr(OpsOrchestrator, "orchestrate"))

    def test_orchestrate_signature(self):
        """OpsOrchestrator.orchestrate has expected signature."""
        from orchestrators.ops_orchestrator import OpsOrchestrator
        import inspect

        sig = inspect.signature(OpsOrchestrator.orchestrate)
        param_names = list(sig.parameters.keys())

        # Should match Orchestrator protocol
        assert "instance_id" in param_names or "target_id" in param_names
        assert "plan" in param_names
        assert "context" in param_names


class TestOpsResult:
    """Test OpsResult dataclass."""

    def test_ops_result_has_success_field(self):
        """OpsResult has success field."""
        from orchestrators.ops_orchestrator import OpsResult

        result = OpsResult(success=True, step_results=[])
        assert hasattr(result, "success")
        assert result.success is True

    def test_ops_result_has_step_results_field(self):
        """OpsResult has step_results field."""
        from orchestrators.ops_orchestrator import OpsResult

        result = OpsResult(success=True, step_results=[])
        assert hasattr(result, "step_results")
        assert isinstance(result.step_results, list)

    def test_ops_result_is_dataclass(self):
        """OpsResult is a dataclass."""
        from orchestrators.ops_orchestrator import OpsResult

        assert hasattr(OpsResult, "__dataclass_fields__")


class TestOpsOrchestratorEmptyPlan:
    """Test OpsOrchestrator with empty plans."""

    def test_empty_plan_returns_success(self):
        """Empty plan should return success."""
        from orchestrators.ops_orchestrator import OpsOrchestrator

        mock_executor = MagicMock()
        orchestrator = OpsOrchestrator(executor=mock_executor)
        plan = MockOpsPlan(steps=[])

        result = orchestrator.orchestrate("target-id", plan, {})

        assert result.success is True
        assert len(result.step_results) == 0
