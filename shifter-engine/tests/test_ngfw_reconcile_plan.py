"""Tests for NGFWReconcilePlan - TDD: Write tests first, all must fail initially.

NGFWReconcilePlan handles drift detection between DB and EC2:
- Compare DB state vs actual EC2 state
- Detect drift (DB says active, EC2 says stopped)
- Publish metrics (NGFWCount)
"""

from dataclasses import dataclass
from typing import Optional, List

import pytest


@dataclass
class MockNGFWReconcileInstance:
    """Mock instance for testing get_context."""

    instance_ids: List[str] = None
    expected_states: dict = None  # instance_id -> expected_state from DB

    def __post_init__(self):
        if self.instance_ids is None:
            self.instance_ids = ["i-12345", "i-67890"]
        if self.expected_states is None:
            self.expected_states = {"i-12345": "running", "i-67890": "stopped"}


class TestNGFWReconcilePlanSteps:
    """Test NGFWReconcilePlan step definitions."""

    def test_has_expected_steps(self):
        """NGFWReconcilePlan should have state check and metrics steps."""
        from plans.ngfw_reconcile import NGFWReconcilePlan

        plan = NGFWReconcilePlan()
        assert len(plan.steps) >= 1

    def test_has_check_state_step(self):
        """Plan should include state check step."""
        from plans.ngfw_reconcile import NGFWReconcilePlan

        plan = NGFWReconcilePlan()
        step_names = [s.name for s in plan.steps]
        assert any("state" in name.lower() or "check" in name.lower() for name in step_names)

    def test_all_steps_have_names(self):
        """All steps must have names."""
        from plans.ngfw_reconcile import NGFWReconcilePlan

        plan = NGFWReconcilePlan()
        for step in plan.steps:
            assert step.name, "Step must have a name"

    def test_all_steps_have_scripts(self):
        """All steps must have script content."""
        from plans.ngfw_reconcile import NGFWReconcilePlan

        plan = NGFWReconcilePlan()
        for step in plan.steps:
            assert step.script, f"Step {step.name} must have a script"

    def test_all_steps_have_timeouts(self):
        """All steps must have positive timeouts."""
        from plans.ngfw_reconcile import NGFWReconcilePlan

        plan = NGFWReconcilePlan()
        for step in plan.steps:
            assert step.timeout_seconds > 0


class TestNGFWReconcilePlanScripts:
    """Test NGFWReconcilePlan script content."""

    def test_check_script_uses_aws_cli(self):
        """Check script should use AWS CLI for EC2 state."""
        from plans.ngfw_reconcile import NGFWReconcilePlan

        plan = NGFWReconcilePlan()
        check_step = next(s for s in plan.steps if "state" in s.name.lower() or "check" in s.name.lower())

        assert "aws" in check_step.script.lower()
        assert "describe-instances" in check_step.script.lower()

    def test_check_script_gets_instance_state(self):
        """Check script should query instance state."""
        from plans.ngfw_reconcile import NGFWReconcilePlan

        plan = NGFWReconcilePlan()
        check_step = next(s for s in plan.steps if "state" in s.name.lower() or "check" in s.name.lower())

        assert "State" in check_step.script or "state" in check_step.script.lower()


class TestNGFWReconcilePlanContext:
    """Test NGFWReconcilePlan.get_context method."""

    def test_get_context_returns_instance_ids(self):
        """get_context should return instance_ids."""
        from plans.ngfw_reconcile import NGFWReconcilePlan

        plan = NGFWReconcilePlan()
        instance = MockNGFWReconcileInstance(instance_ids=["i-11111", "i-22222"])
        context = plan.get_context(instance)

        assert "instance_ids" in context

    def test_get_context_missing_instance_ids_raises(self):
        """get_context should raise if instance_ids is missing."""
        from plans.ngfw_reconcile import NGFWReconcilePlan

        plan = NGFWReconcilePlan()
        instance = MockNGFWReconcileInstance()
        instance.instance_ids = None

        with pytest.raises(ValueError, match="instance_ids"):
            plan.get_context(instance)


class TestNGFWReconcilePlanInterface:
    """Test NGFWReconcilePlan interface compliance."""

    def test_has_steps_attribute(self):
        """NGFWReconcilePlan should have steps attribute."""
        from plans.ngfw_reconcile import NGFWReconcilePlan

        plan = NGFWReconcilePlan()
        assert hasattr(plan, "steps")
        assert isinstance(plan.steps, list)

    def test_has_verify_step_attribute(self):
        """NGFWReconcilePlan should have verify_step attribute."""
        from plans.ngfw_reconcile import NGFWReconcilePlan

        plan = NGFWReconcilePlan()
        assert hasattr(plan, "verify_step")

    def test_has_get_context_method(self):
        """NGFWReconcilePlan should have get_context method."""
        from plans.ngfw_reconcile import NGFWReconcilePlan

        plan = NGFWReconcilePlan()
        assert hasattr(plan, "get_context")
        assert callable(plan.get_context)
