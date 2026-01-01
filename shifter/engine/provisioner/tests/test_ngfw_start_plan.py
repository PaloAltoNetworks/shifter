"""Tests for NGFWStartPlan - TDD: Write tests first, all must fail initially.

NGFWStartPlan handles starting a stopped NGFW instance using AWSExecutor:
- Start EC2 instance via AWSExecutor.start_instance()
- Wait for running state via AWSExecutor.wait_for_running()

This plan uses AWSExecutor for AWS API calls, not bash scripts.
"""

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest


@dataclass
class MockNGFWInstance:
    """Mock NGFW instance for testing get_context."""

    instance_id: str = "i-12345"


class TestNGFWStartPlanSteps:
    """Test NGFWStartPlan step definitions."""

    def test_has_expected_steps(self):
        """NGFWStartPlan should have start and wait steps."""
        from plans.ngfw_start import NGFWStartPlan

        plan = NGFWStartPlan()
        assert len(plan.steps) >= 2

    def test_has_start_instance_step(self):
        """Plan should include EC2 start step."""
        from plans.ngfw_start import NGFWStartPlan

        plan = NGFWStartPlan()
        step_names = [s.name for s in plan.steps]
        assert any("start" in name.lower() for name in step_names)

    def test_has_wait_running_step(self):
        """Plan should include wait for running step."""
        from plans.ngfw_start import NGFWStartPlan

        plan = NGFWStartPlan()
        step_names = [s.name for s in plan.steps]
        assert any("running" in name.lower() or "wait" in name.lower() for name in step_names)

    def test_start_before_wait(self):
        """Start must come before wait steps."""
        from plans.ngfw_start import NGFWStartPlan

        plan = NGFWStartPlan()
        step_names = [s.name for s in plan.steps]

        start_idx = next(i for i, n in enumerate(step_names) if "start" in n.lower())
        wait_idx = next(
            i for i, n in enumerate(step_names)
            if "running" in n.lower() or ("wait" in n.lower() and "start" not in n.lower())
        )
        assert start_idx < wait_idx

    def test_all_steps_have_names(self):
        """All steps must have names."""
        from plans.ngfw_start import NGFWStartPlan

        plan = NGFWStartPlan()
        for step in plan.steps:
            assert step.name, "Step must have a name"

    def test_all_steps_have_action(self):
        """All steps must have action attribute (AWSExecutor method name)."""
        from plans.ngfw_start import NGFWStartPlan

        plan = NGFWStartPlan()
        for step in plan.steps:
            assert hasattr(step, "action"), f"Step {step.name} must have action attribute"
            assert step.action, f"Step {step.name} must have non-empty action"

    def test_all_steps_have_params(self):
        """All steps must have params attribute (context keys to pass)."""
        from plans.ngfw_start import NGFWStartPlan

        plan = NGFWStartPlan()
        for step in plan.steps:
            assert hasattr(step, "params"), f"Step {step.name} must have params attribute"


class TestNGFWStartPlanAWSExecutorActions:
    """Test NGFWStartPlan uses AWSExecutor method names."""

    def test_start_step_uses_start_instance_action(self):
        """Start step should use AWSExecutor.start_instance action."""
        from plans.ngfw_start import NGFWStartPlan

        plan = NGFWStartPlan()
        start_step = next(s for s in plan.steps if "start" in s.name.lower())

        assert start_step.action == "start_instance"

    def test_start_step_params_include_instance_id(self):
        """Start step params should include instance_id."""
        from plans.ngfw_start import NGFWStartPlan

        plan = NGFWStartPlan()
        start_step = next(s for s in plan.steps if "start" in s.name.lower())

        assert "instance_id" in start_step.params

    def test_wait_step_uses_wait_for_running_action(self):
        """Wait step should use AWSExecutor.wait_for_running action."""
        from plans.ngfw_start import NGFWStartPlan

        plan = NGFWStartPlan()
        wait_step = next(s for s in plan.steps if "running" in s.name.lower() or "wait" in s.name.lower())

        assert wait_step.action == "wait_for_running"

    def test_wait_step_params_include_instance_id(self):
        """Wait step params should include instance_id."""
        from plans.ngfw_start import NGFWStartPlan

        plan = NGFWStartPlan()
        wait_step = next(s for s in plan.steps if "running" in s.name.lower() or "wait" in s.name.lower())

        assert "instance_id" in wait_step.params


class TestNGFWStartPlanContext:
    """Test NGFWStartPlan.get_context method."""

    def test_get_context_returns_instance_id(self):
        """get_context should return instance_id."""
        from plans.ngfw_start import NGFWStartPlan

        plan = NGFWStartPlan()
        instance = MockNGFWInstance(instance_id="i-99999")
        context = plan.get_context(instance)

        assert "instance_id" in context
        assert context["instance_id"] == "i-99999"

    def test_get_context_missing_instance_id_raises(self):
        """get_context should raise if instance_id is missing."""
        from plans.ngfw_start import NGFWStartPlan

        plan = NGFWStartPlan()
        instance = MockNGFWInstance()
        instance.instance_id = None

        with pytest.raises(ValueError, match="instance_id"):
            plan.get_context(instance)


class TestNGFWStartPlanInterface:
    """Test NGFWStartPlan interface compliance."""

    def test_has_steps_attribute(self):
        """NGFWStartPlan should have steps attribute."""
        from plans.ngfw_start import NGFWStartPlan

        plan = NGFWStartPlan()
        assert hasattr(plan, "steps")
        assert isinstance(plan.steps, list)

    def test_has_name_attribute(self):
        """NGFWStartPlan should have name attribute."""
        from plans.ngfw_start import NGFWStartPlan

        plan = NGFWStartPlan()
        assert hasattr(plan, "name")
        assert plan.name == "ngfw_start"

    def test_has_get_context_method(self):
        """NGFWStartPlan should have get_context method."""
        from plans.ngfw_start import NGFWStartPlan

        plan = NGFWStartPlan()
        assert hasattr(plan, "get_context")
        assert callable(plan.get_context)


class TestNGFWStartPlanExecution:
    """Test NGFWStartPlan can be executed with AWSExecutor."""

    def test_execute_start_step_calls_aws_executor(self):
        """Execute start step should call AWSExecutor.start_instance."""
        from plans.ngfw_start import NGFWStartPlan

        plan = NGFWStartPlan()
        start_step = next(s for s in plan.steps if "start" in s.name.lower())

        # Mock AWSExecutor
        mock_executor = MagicMock()
        mock_executor.start_instance.return_value = MagicMock(success=True, stdout="{}", stderr="")

        # Build params from context
        context = {"instance_id": "i-12345"}
        params = {k: context[k] for k in start_step.params}

        # Call the executor method
        method = getattr(mock_executor, start_step.action)
        result = method(**params)

        mock_executor.start_instance.assert_called_once_with(instance_id="i-12345")
        assert result.success is True

    def test_execute_wait_step_calls_aws_executor(self):
        """Execute wait step should call AWSExecutor.wait_for_running."""
        from plans.ngfw_start import NGFWStartPlan

        plan = NGFWStartPlan()
        wait_step = next(s for s in plan.steps if "running" in s.name.lower() or "wait" in s.name.lower())

        # Mock AWSExecutor
        mock_executor = MagicMock()
        mock_executor.wait_for_running.return_value = MagicMock(success=True, stdout="running", stderr="")

        # Build params from context
        context = {"instance_id": "i-12345"}
        params = {k: context[k] for k in wait_step.params}

        # Call the executor method
        method = getattr(mock_executor, wait_step.action)
        result = method(**params)

        mock_executor.wait_for_running.assert_called_once_with(instance_id="i-12345")
        assert result.success is True
