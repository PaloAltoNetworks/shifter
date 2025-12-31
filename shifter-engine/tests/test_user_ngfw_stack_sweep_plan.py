"""Tests for UserNGFWStackSweepPlan - TDD: Write tests first, all must fail initially.

UserNGFWStackSweepPlan handles idle NGFW detection using AWSExecutor:
- Describe instances via AWSExecutor.describe_instances() to get current states
- Return instance states for orchestrator to determine idle status
- Orchestrator compares with DB activity data to identify idle instances

This plan uses AWSExecutor for AWS API calls, not bash scripts.
"""

from dataclasses import dataclass
from typing import List, Dict
from unittest.mock import MagicMock

import pytest


@dataclass
class MockSweepInstance:
    """Mock instance for testing get_context."""

    instance_ids: List[str] = None
    idle_threshold_minutes: int = 60

    def __post_init__(self):
        if self.instance_ids is None:
            self.instance_ids = ["i-12345", "i-67890"]


class TestUserNGFWStackSweepPlanSteps:
    """Test UserNGFWStackSweepPlan step definitions."""

    def test_has_expected_steps(self):
        """UserNGFWStackSweepPlan should have describe instances step."""
        from plans.user_ngfw_stack_sweep import UserNGFWStackSweepPlan

        plan = UserNGFWStackSweepPlan()
        assert len(plan.steps) >= 1

    def test_has_describe_instances_step(self):
        """Plan should include describe instances step."""
        from plans.user_ngfw_stack_sweep import UserNGFWStackSweepPlan

        plan = UserNGFWStackSweepPlan()
        step_names = [s.name for s in plan.steps]
        assert any("describe" in name.lower() or "instance" in name.lower() for name in step_names)

    def test_all_steps_have_names(self):
        """All steps must have names."""
        from plans.user_ngfw_stack_sweep import UserNGFWStackSweepPlan

        plan = UserNGFWStackSweepPlan()
        for step in plan.steps:
            assert step.name, "Step must have a name"

    def test_all_steps_have_action(self):
        """All steps must have action attribute (AWSExecutor method name)."""
        from plans.user_ngfw_stack_sweep import UserNGFWStackSweepPlan

        plan = UserNGFWStackSweepPlan()
        for step in plan.steps:
            assert hasattr(step, "action"), f"Step {step.name} must have action attribute"
            assert step.action, f"Step {step.name} must have non-empty action"

    def test_all_steps_have_params(self):
        """All steps must have params attribute (context keys to pass)."""
        from plans.user_ngfw_stack_sweep import UserNGFWStackSweepPlan

        plan = UserNGFWStackSweepPlan()
        for step in plan.steps:
            assert hasattr(step, "params"), f"Step {step.name} must have params attribute"


class TestUserNGFWStackSweepPlanAWSExecutorActions:
    """Test UserNGFWStackSweepPlan uses AWSExecutor method names."""

    def test_describe_step_uses_describe_instances_action(self):
        """Describe step should use AWSExecutor.describe_instances action."""
        from plans.user_ngfw_stack_sweep import UserNGFWStackSweepPlan

        plan = UserNGFWStackSweepPlan()
        describe_step = next(s for s in plan.steps if "describe" in s.name.lower() or "instance" in s.name.lower())

        assert describe_step.action == "describe_instances"

    def test_describe_step_params_include_instance_ids(self):
        """Describe step params should include instance_ids."""
        from plans.user_ngfw_stack_sweep import UserNGFWStackSweepPlan

        plan = UserNGFWStackSweepPlan()
        describe_step = next(s for s in plan.steps if "describe" in s.name.lower() or "instance" in s.name.lower())

        assert "instance_ids" in describe_step.params


class TestUserNGFWStackSweepPlanContext:
    """Test UserNGFWStackSweepPlan.get_context method."""

    def test_get_context_returns_instance_ids(self):
        """get_context should return instance_ids as list."""
        from plans.user_ngfw_stack_sweep import UserNGFWStackSweepPlan

        plan = UserNGFWStackSweepPlan()
        instance = MockSweepInstance(instance_ids=["i-11111", "i-22222"])
        context = plan.get_context(instance)

        assert "instance_ids" in context
        assert context["instance_ids"] == ["i-11111", "i-22222"]

    def test_get_context_returns_idle_threshold(self):
        """get_context should return idle_threshold_minutes."""
        from plans.user_ngfw_stack_sweep import UserNGFWStackSweepPlan

        plan = UserNGFWStackSweepPlan()
        instance = MockSweepInstance(idle_threshold_minutes=120)
        context = plan.get_context(instance)

        assert "idle_threshold_minutes" in context
        assert context["idle_threshold_minutes"] == 120

    def test_get_context_missing_instance_ids_raises(self):
        """get_context should raise if instance_ids is missing."""
        from plans.user_ngfw_stack_sweep import UserNGFWStackSweepPlan

        plan = UserNGFWStackSweepPlan()
        instance = MockSweepInstance()
        instance.instance_ids = None

        with pytest.raises(ValueError, match="instance_ids"):
            plan.get_context(instance)

    def test_get_context_empty_instance_ids_allowed(self):
        """get_context should allow empty instance_ids list."""
        from plans.user_ngfw_stack_sweep import UserNGFWStackSweepPlan

        plan = UserNGFWStackSweepPlan()
        instance = MockSweepInstance(instance_ids=[])
        context = plan.get_context(instance)

        assert context["instance_ids"] == []


class TestUserNGFWStackSweepPlanInterface:
    """Test UserNGFWStackSweepPlan interface compliance."""

    def test_has_steps_attribute(self):
        """UserNGFWStackSweepPlan should have steps attribute."""
        from plans.user_ngfw_stack_sweep import UserNGFWStackSweepPlan

        plan = UserNGFWStackSweepPlan()
        assert hasattr(plan, "steps")
        assert isinstance(plan.steps, list)

    def test_has_name_attribute(self):
        """UserNGFWStackSweepPlan should have name attribute."""
        from plans.user_ngfw_stack_sweep import UserNGFWStackSweepPlan

        plan = UserNGFWStackSweepPlan()
        assert hasattr(plan, "name")
        assert plan.name == "user_ngfw_stack_sweep"

    def test_has_get_context_method(self):
        """UserNGFWStackSweepPlan should have get_context method."""
        from plans.user_ngfw_stack_sweep import UserNGFWStackSweepPlan

        plan = UserNGFWStackSweepPlan()
        assert hasattr(plan, "get_context")
        assert callable(plan.get_context)


class TestUserNGFWStackSweepPlanExecution:
    """Test UserNGFWStackSweepPlan can be executed with AWSExecutor."""

    def test_execute_describe_step_calls_aws_executor(self):
        """Execute describe step should call AWSExecutor.describe_instances."""
        from plans.user_ngfw_stack_sweep import UserNGFWStackSweepPlan

        plan = UserNGFWStackSweepPlan()
        describe_step = next(s for s in plan.steps if "describe" in s.name.lower() or "instance" in s.name.lower())

        # Mock AWSExecutor
        mock_executor = MagicMock()
        mock_executor.describe_instances.return_value = MagicMock(
            success=True,
            stdout='{"Reservations": [{"Instances": [{"InstanceId": "i-12345", "State": {"Name": "running"}}]}]}',
            stderr="",
        )

        # Build params from context
        context = {"instance_ids": ["i-12345", "i-67890"]}
        params = {k: context[k] for k in describe_step.params}

        # Call the executor method
        method = getattr(mock_executor, describe_step.action)
        result = method(**params)

        mock_executor.describe_instances.assert_called_once_with(instance_ids=["i-12345", "i-67890"])
        assert result.success is True
