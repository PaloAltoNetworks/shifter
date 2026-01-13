"""Tests for OpsOrchestrator - TDD: Write tests first, all must fail initially.

OpsOrchestrator handles runtime operations like:
- Starting/stopping instances
- Managing routes
- Executing operational plans
"""

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock


@dataclass
class MockOpsPlan:
    """Mock operations plan for testing."""

    steps: list[Any]
    name: str = "mock_ops_plan"

    def get_context(self, target: Any) -> dict[str, Any]:
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
        import inspect

        from orchestrators.ops_orchestrator import OpsOrchestrator

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
        # First call succeeds, second fails (using execute_action)
        mock_executor.execute_action.side_effect = [
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
        from orchestrators.base import StepResult
        from orchestrators.ops_orchestrator import OpsOrchestrator

        mock_executor = MagicMock()
        mock_executor.execute_action.return_value = MagicMock(success=True, stdout="output", stderr="")

        @dataclass
        class MockStep:
            name: str
            action: str
            params: dict

        plan = MockOpsPlan(steps=[MockStep(name="test_step", action="test", params={})])

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
        assert callable(OpsOrchestrator.orchestrate)

    def test_orchestrate_signature(self):
        """OpsOrchestrator.orchestrate has expected signature."""
        import inspect

        from orchestrators.ops_orchestrator import OpsOrchestrator

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


# =============================================================================
# Integration Tests: OpsOrchestrator with AWSExecutor.execute_action()
# =============================================================================


class TestOpsOrchestratorAWSExecutorIntegration:
    """Test OpsOrchestrator uses AWSExecutor.execute_action() when available."""

    def test_uses_execute_action_when_available(self):
        """OpsOrchestrator uses execute_action() for AWSExecutor."""
        from orchestrators.ops_orchestrator import OpsOrchestrator

        mock_executor = MagicMock()
        mock_executor.execute_action.return_value = MagicMock(success=True, stdout="ok", stderr="")

        @dataclass
        class MockStep:
            name: str
            action: str
            params: list

        plan = MockOpsPlan(steps=[MockStep(name="start", action="start_instance", params=["instance_id"])])
        context = {"instance_id": "i-12345"}

        orchestrator = OpsOrchestrator(executor=mock_executor)
        result = orchestrator.orchestrate("i-12345", plan, context)

        mock_executor.execute_action.assert_called_once_with("start_instance", context)
        assert result.success is True

    def test_passes_context_to_execute_action(self):
        """OpsOrchestrator passes context dict to execute_action()."""
        from orchestrators.ops_orchestrator import OpsOrchestrator

        mock_executor = MagicMock()
        mock_executor.execute_action.return_value = MagicMock(success=True, stdout="ok", stderr="")

        @dataclass
        class MockStep:
            name: str
            action: str
            params: list

        plan = MockOpsPlan(
            steps=[
                MockStep(name="start", action="start_instance", params=["instance_id"]),
                MockStep(name="wait", action="wait_for_running", params=["instance_id"]),
            ]
        )
        context = {"instance_id": "i-12345", "timeout": 300}

        orchestrator = OpsOrchestrator(executor=mock_executor)
        result = orchestrator.orchestrate("i-12345", plan, context)

        assert mock_executor.execute_action.call_count == 2
        # Both calls should receive the same context
        for call in mock_executor.execute_action.call_args_list:
            assert call[0][1] == context
        assert result.success is True

    def test_falls_back_to_run_command_without_execute_action(self):
        """OpsOrchestrator falls back to run_command() if no execute_action."""
        from orchestrators.ops_orchestrator import OpsOrchestrator

        mock_executor = MagicMock(spec=["run_command"])  # No execute_action
        mock_executor.run_command.return_value = MagicMock(success=True, stdout="ok", stderr="")

        @dataclass
        class MockStep:
            name: str
            action: str
            params: dict

        plan = MockOpsPlan(steps=[MockStep(name="test", action="test_action", params={})])

        orchestrator = OpsOrchestrator(executor=mock_executor)
        result = orchestrator.orchestrate("target-id", plan, {})

        mock_executor.run_command.assert_called_once()
        assert result.success is True

    def test_handles_execute_action_failure(self):
        """OpsOrchestrator handles execute_action() failures properly."""
        from orchestrators.ops_orchestrator import OpsOrchestrator

        mock_executor = MagicMock()
        mock_executor.execute_action.return_value = MagicMock(success=False, stdout="", stderr="Instance not found")

        @dataclass
        class MockStep:
            name: str
            action: str
            params: list

        plan = MockOpsPlan(steps=[MockStep(name="start", action="start_instance", params=["instance_id"])])
        context = {"instance_id": "i-invalid"}

        orchestrator = OpsOrchestrator(executor=mock_executor)
        result = orchestrator.orchestrate("i-invalid", plan, context)

        assert result.success is False
        assert len(result.step_results) == 1
        assert result.step_results[0].stderr == "Instance not found"


class TestOpsOrchestratorWithNGFWPlans:
    """Test OpsOrchestrator with NGFW start/stop plans."""

    def test_executes_ngfw_start_plan(self):
        """OpsOrchestrator executes NGFWStartPlan steps."""
        from orchestrators.ops_orchestrator import OpsOrchestrator
        from plans.ngfw_start import NGFWStartPlan

        mock_executor = MagicMock()
        mock_executor.execute_action.return_value = MagicMock(success=True, stdout="ok", stderr="")

        plan = NGFWStartPlan()
        context = {"instance_id": "i-12345"}

        orchestrator = OpsOrchestrator(executor=mock_executor)
        result = orchestrator.orchestrate("i-12345", plan, context)

        # NGFWStartPlan has 2 steps: start_instance and wait_for_running
        assert mock_executor.execute_action.call_count == 2
        actions = [call[0][0] for call in mock_executor.execute_action.call_args_list]
        assert "start_instance" in actions
        assert "wait_for_running" in actions
        assert result.success is True

    def test_executes_ngfw_stop_plan(self):
        """OpsOrchestrator executes NGFWStopPlan steps."""
        from orchestrators.ops_orchestrator import OpsOrchestrator
        from plans.ngfw_stop import NGFWStopPlan

        mock_executor = MagicMock()
        mock_executor.execute_action.return_value = MagicMock(success=True, stdout="ok", stderr="")

        plan = NGFWStopPlan()
        context = {"instance_id": "i-12345"}

        orchestrator = OpsOrchestrator(executor=mock_executor)
        result = orchestrator.orchestrate("i-12345", plan, context)

        # NGFWStopPlan has 2 steps: stop_instance and wait_for_stopped
        assert mock_executor.execute_action.call_count == 2
        actions = [call[0][0] for call in mock_executor.execute_action.call_args_list]
        assert "stop_instance" in actions
        assert "wait_for_stopped" in actions
        assert result.success is True
