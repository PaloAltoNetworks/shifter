"""Tests for NGFWStopPlan - TDD: Write tests first, all must fail initially.

NGFWStopPlan handles stopping a running NGFW instance using AWSExecutor:
- Stop EC2 instance via AWSExecutor.stop_instance()
- Wait for stopped state via AWSExecutor.wait_for_stopped()

This plan uses AWSExecutor for AWS API calls, not bash scripts.
"""

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest


@dataclass
class MockNGFWInstance:
    """Mock NGFW instance for testing get_context."""

    instance_id: str = "i-12345"


class TestNGFWStopPlanSteps:
    """Test NGFWStopPlan step definitions."""

    def test_has_expected_steps(self):
        """NGFWStopPlan should have stop and wait steps."""
        from plans.ngfw_stop import NGFWStopPlan

        plan = NGFWStopPlan()
        assert len(plan.steps) >= 2

    def test_has_stop_instance_step(self):
        """Plan should include EC2 stop step."""
        from plans.ngfw_stop import NGFWStopPlan

        plan = NGFWStopPlan()
        step_names = [s.name for s in plan.steps]
        assert any("stop" in name.lower() for name in step_names)

    def test_has_wait_stopped_step(self):
        """Plan should include wait for stopped step."""
        from plans.ngfw_stop import NGFWStopPlan

        plan = NGFWStopPlan()
        step_names = [s.name for s in plan.steps]
        assert any("stopped" in name.lower() or "wait" in name.lower() for name in step_names)

    def test_stop_before_wait(self):
        """Stop must come before wait step."""
        from plans.ngfw_stop import NGFWStopPlan

        plan = NGFWStopPlan()
        step_names = [s.name for s in plan.steps]

        stop_idx = next(i for i, n in enumerate(step_names) if "stop" in n.lower() and "wait" not in n.lower())
        wait_idx = next(
            i for i, n in enumerate(step_names)
            if "stopped" in n.lower() or ("wait" in n.lower())
        )
        assert stop_idx < wait_idx

    def test_all_steps_have_names(self):
        """All steps must have names."""
        from plans.ngfw_stop import NGFWStopPlan

        plan = NGFWStopPlan()
        for step in plan.steps:
            assert step.name, "Step must have a name"

    def test_all_steps_have_action(self):
        """All steps must have action attribute (AWSExecutor method name)."""
        from plans.ngfw_stop import NGFWStopPlan

        plan = NGFWStopPlan()
        for step in plan.steps:
            assert hasattr(step, "action"), f"Step {step.name} must have action attribute"
            assert step.action, f"Step {step.name} must have non-empty action"

    def test_all_steps_have_params(self):
        """All steps must have params attribute (context keys to pass)."""
        from plans.ngfw_stop import NGFWStopPlan

        plan = NGFWStopPlan()
        for step in plan.steps:
            assert hasattr(step, "params"), f"Step {step.name} must have params attribute"


class TestNGFWStopPlanAWSExecutorActions:
    """Test NGFWStopPlan uses AWSExecutor method names."""

    def test_stop_step_uses_stop_instance_action(self):
        """Stop step should use AWSExecutor.stop_instance action."""
        from plans.ngfw_stop import NGFWStopPlan

        plan = NGFWStopPlan()
        stop_step = next(s for s in plan.steps if "stop" in s.name.lower() and "wait" not in s.name.lower())

        assert stop_step.action == "stop_instance"

    def test_stop_step_params_include_instance_id(self):
        """Stop step params should include instance_id."""
        from plans.ngfw_stop import NGFWStopPlan

        plan = NGFWStopPlan()
        stop_step = next(s for s in plan.steps if "stop" in s.name.lower() and "wait" not in s.name.lower())

        assert "instance_id" in stop_step.params

    def test_wait_step_uses_wait_for_stopped_action(self):
        """Wait step should use AWSExecutor.wait_for_stopped action."""
        from plans.ngfw_stop import NGFWStopPlan

        plan = NGFWStopPlan()
        wait_step = next(s for s in plan.steps if "stopped" in s.name.lower() or "wait" in s.name.lower())

        assert wait_step.action == "wait_for_stopped"

    def test_wait_step_params_include_instance_id(self):
        """Wait step params should include instance_id."""
        from plans.ngfw_stop import NGFWStopPlan

        plan = NGFWStopPlan()
        wait_step = next(s for s in plan.steps if "stopped" in s.name.lower() or "wait" in s.name.lower())

        assert "instance_id" in wait_step.params


class TestNGFWStopPlanContext:
    """Test NGFWStopPlan.get_context method."""

    def test_get_context_returns_instance_id(self):
        """get_context should return instance_id."""
        from plans.ngfw_stop import NGFWStopPlan

        plan = NGFWStopPlan()
        instance = MockNGFWInstance(instance_id="i-99999")
        context = plan.get_context(instance)

        assert "instance_id" in context
        assert context["instance_id"] == "i-99999"

    def test_get_context_missing_instance_id_raises(self):
        """get_context should raise if instance_id is missing."""
        from plans.ngfw_stop import NGFWStopPlan

        plan = NGFWStopPlan()
        instance = MockNGFWInstance()
        instance.instance_id = None

        with pytest.raises(ValueError, match="instance_id"):
            plan.get_context(instance)


class TestNGFWStopPlanInterface:
    """Test NGFWStopPlan interface compliance."""

    def test_has_steps_attribute(self):
        """NGFWStopPlan should have steps attribute."""
        from plans.ngfw_stop import NGFWStopPlan

        plan = NGFWStopPlan()
        assert hasattr(plan, "steps")
        assert isinstance(plan.steps, list)

    def test_has_name_attribute(self):
        """NGFWStopPlan should have name attribute."""
        from plans.ngfw_stop import NGFWStopPlan

        plan = NGFWStopPlan()
        assert hasattr(plan, "name")
        assert plan.name == "ngfw_stop"

    def test_has_get_context_method(self):
        """NGFWStopPlan should have get_context method."""
        from plans.ngfw_stop import NGFWStopPlan

        plan = NGFWStopPlan()
        assert hasattr(plan, "get_context")
        assert callable(plan.get_context)


class TestNGFWStopPlanExecution:
    """Test NGFWStopPlan can be executed with AWSExecutor."""

    def test_execute_stop_step_calls_aws_executor(self):
        """Execute stop step should call AWSExecutor.stop_instance."""
        from plans.ngfw_stop import NGFWStopPlan

        plan = NGFWStopPlan()
        stop_step = next(s for s in plan.steps if "stop" in s.name.lower() and "wait" not in s.name.lower())

        # Mock AWSExecutor
        mock_executor = MagicMock()
        mock_executor.stop_instance.return_value = MagicMock(success=True, stdout="{}", stderr="")

        # Build params from context
        context = {"instance_id": "i-12345"}
        params = {k: context[k] for k in stop_step.params}

        # Call the executor method
        method = getattr(mock_executor, stop_step.action)
        result = method(**params)

        mock_executor.stop_instance.assert_called_once_with(instance_id="i-12345")
        assert result.success is True

    def test_execute_wait_step_calls_aws_executor(self):
        """Execute wait step should call AWSExecutor.wait_for_stopped."""
        from plans.ngfw_stop import NGFWStopPlan

        plan = NGFWStopPlan()
        wait_step = next(s for s in plan.steps if "stopped" in s.name.lower() or "wait" in s.name.lower())

        # Mock AWSExecutor
        mock_executor = MagicMock()
        mock_executor.wait_for_stopped.return_value = MagicMock(success=True, stdout="stopped", stderr="")

        # Build params from context
        context = {"instance_id": "i-12345"}
        params = {k: context[k] for k in wait_step.params}

        # Call the executor method
        method = getattr(mock_executor, wait_step.action)
        result = method(**params)

        mock_executor.wait_for_stopped.assert_called_once_with(instance_id="i-12345")
        assert result.success is True
