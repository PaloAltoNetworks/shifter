"""Tests for NGFWReconcilePlan - TDD: Write tests first, all must fail initially.

NGFWReconcilePlan handles drift detection between DB and EC2 using AWSExecutor:
- Describe instances via AWSExecutor.describe_instances()
- Compare DB state vs actual EC2 state
- Return instance states for drift analysis

This plan uses AWSExecutor for AWS API calls, not bash scripts.
"""

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest


@dataclass
class MockNGFWReconcileInstance:
    """Mock instance for testing get_context."""

    instance_ids: list[str] = None

    def __post_init__(self):
        if self.instance_ids is None:
            self.instance_ids = ["i-12345", "i-67890"]


class TestNGFWReconcilePlanSteps:
    """Test NGFWReconcilePlan step definitions."""

    def test_has_expected_steps(self):
        """NGFWReconcilePlan should have describe instances step."""
        from plans.ngfw_reconcile import NGFWReconcilePlan

        plan = NGFWReconcilePlan()
        assert len(plan.steps) >= 1

    def test_has_describe_instances_step(self):
        """Plan should include describe instances step."""
        from plans.ngfw_reconcile import NGFWReconcilePlan

        plan = NGFWReconcilePlan()
        step_names = [s.name for s in plan.steps]
        assert any("describe" in name.lower() or "instance" in name.lower() for name in step_names)

    def test_all_steps_have_names(self):
        """All steps must have names."""
        from plans.ngfw_reconcile import NGFWReconcilePlan

        plan = NGFWReconcilePlan()
        for step in plan.steps:
            assert step.name, "Step must have a name"

    def test_all_steps_have_action(self):
        """All steps must have action attribute (AWSExecutor method name)."""
        from plans.ngfw_reconcile import NGFWReconcilePlan

        plan = NGFWReconcilePlan()
        for step in plan.steps:
            assert hasattr(step, "action"), f"Step {step.name} must have action attribute"
            assert step.action, f"Step {step.name} must have non-empty action"

    def test_all_steps_have_params(self):
        """All steps must have params attribute (context keys to pass)."""
        from plans.ngfw_reconcile import NGFWReconcilePlan

        plan = NGFWReconcilePlan()
        for step in plan.steps:
            assert hasattr(step, "params"), f"Step {step.name} must have params attribute"


class TestNGFWReconcilePlanAWSExecutorActions:
    """Test NGFWReconcilePlan uses AWSExecutor method names."""

    def test_describe_step_uses_describe_instances_action(self):
        """Describe step should use AWSExecutor.describe_instances action."""
        from plans.ngfw_reconcile import NGFWReconcilePlan

        plan = NGFWReconcilePlan()
        describe_step = next(s for s in plan.steps if "describe" in s.name.lower() or "instance" in s.name.lower())

        assert describe_step.action == "describe_instances"

    def test_describe_step_params_include_instance_ids(self):
        """Describe step params should include instance_ids."""
        from plans.ngfw_reconcile import NGFWReconcilePlan

        plan = NGFWReconcilePlan()
        describe_step = next(s for s in plan.steps if "describe" in s.name.lower() or "instance" in s.name.lower())

        assert "instance_ids" in describe_step.params


class TestNGFWReconcilePlanContext:
    """Test NGFWReconcilePlan.get_context method."""

    def test_get_context_returns_instance_ids(self):
        """get_context should return instance_ids as list."""
        from plans.ngfw_reconcile import NGFWReconcilePlan

        plan = NGFWReconcilePlan()
        instance = MockNGFWReconcileInstance(instance_ids=["i-11111", "i-22222"])
        context = plan.get_context(instance)

        assert "instance_ids" in context
        assert context["instance_ids"] == ["i-11111", "i-22222"]

    def test_get_context_missing_instance_ids_raises(self):
        """get_context should raise if instance_ids is missing."""
        from plans.ngfw_reconcile import NGFWReconcilePlan

        plan = NGFWReconcilePlan()
        instance = MockNGFWReconcileInstance()
        instance.instance_ids = None

        with pytest.raises(ValueError, match="instance_ids"):
            plan.get_context(instance)

    def test_get_context_empty_instance_ids_allowed(self):
        """get_context should allow empty instance_ids list."""
        from plans.ngfw_reconcile import NGFWReconcilePlan

        plan = NGFWReconcilePlan()
        instance = MockNGFWReconcileInstance(instance_ids=[])
        context = plan.get_context(instance)

        assert context["instance_ids"] == []


class TestNGFWReconcilePlanInterface:
    """Test NGFWReconcilePlan interface compliance."""

    def test_has_steps_attribute(self):
        """NGFWReconcilePlan should have steps attribute."""
        from plans.ngfw_reconcile import NGFWReconcilePlan

        plan = NGFWReconcilePlan()
        assert hasattr(plan, "steps")
        assert isinstance(plan.steps, list)

    def test_has_name_attribute(self):
        """NGFWReconcilePlan should have name attribute."""
        from plans.ngfw_reconcile import NGFWReconcilePlan

        plan = NGFWReconcilePlan()
        assert hasattr(plan, "name")
        assert plan.name == "ngfw_reconcile"

    def test_has_get_context_method(self):
        """NGFWReconcilePlan should have get_context method."""
        from plans.ngfw_reconcile import NGFWReconcilePlan

        plan = NGFWReconcilePlan()
        assert hasattr(plan, "get_context")
        assert callable(plan.get_context)


class TestNGFWReconcilePlanExecution:
    """Test NGFWReconcilePlan can be executed with AWSExecutor."""

    def test_execute_describe_step_calls_aws_executor(self):
        """Execute describe step should call AWSExecutor.describe_instances."""
        from plans.ngfw_reconcile import NGFWReconcilePlan

        plan = NGFWReconcilePlan()
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
