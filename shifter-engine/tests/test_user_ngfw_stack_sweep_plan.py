"""Tests for UserNGFWStackSweepPlan - TDD: Write tests first, all must fail initially.

UserNGFWStackSweepPlan handles idle NGFW detection and cleanup:
- Check for idle NGFWs (no active ranges)
- Trigger stop for idle instances
- Reconcile endpoints
"""

from dataclasses import dataclass
from typing import Optional, List, Dict

import pytest


@dataclass
class MockSweepInstance:
    """Mock instance for testing get_context."""

    ngfw_instances: List[Dict] = None  # List of {instance_id, user_id, last_activity}
    idle_threshold_minutes: int = 60

    def __post_init__(self):
        if self.ngfw_instances is None:
            self.ngfw_instances = [
                {"instance_id": "i-12345", "user_id": "user-1", "last_activity": "2024-01-01T00:00:00Z"},
                {"instance_id": "i-67890", "user_id": "user-2", "last_activity": "2024-01-01T00:00:00Z"},
            ]


class TestUserNGFWStackSweepPlanSteps:
    """Test UserNGFWStackSweepPlan step definitions."""

    def test_has_expected_steps(self):
        """UserNGFWStackSweepPlan should have idle check step."""
        from plans.user_ngfw_stack_sweep import UserNGFWStackSweepPlan

        plan = UserNGFWStackSweepPlan()
        assert len(plan.steps) >= 1

    def test_has_check_idle_step(self):
        """Plan should include idle detection step."""
        from plans.user_ngfw_stack_sweep import UserNGFWStackSweepPlan

        plan = UserNGFWStackSweepPlan()
        step_names = [s.name for s in plan.steps]
        assert any("idle" in name.lower() or "check" in name.lower() for name in step_names)

    def test_all_steps_have_names(self):
        """All steps must have names."""
        from plans.user_ngfw_stack_sweep import UserNGFWStackSweepPlan

        plan = UserNGFWStackSweepPlan()
        for step in plan.steps:
            assert step.name, "Step must have a name"

    def test_all_steps_have_scripts(self):
        """All steps must have script content."""
        from plans.user_ngfw_stack_sweep import UserNGFWStackSweepPlan

        plan = UserNGFWStackSweepPlan()
        for step in plan.steps:
            assert step.script, f"Step {step.name} must have a script"

    def test_all_steps_have_timeouts(self):
        """All steps must have positive timeouts."""
        from plans.user_ngfw_stack_sweep import UserNGFWStackSweepPlan

        plan = UserNGFWStackSweepPlan()
        for step in plan.steps:
            assert step.timeout_seconds > 0


class TestUserNGFWStackSweepPlanScripts:
    """Test UserNGFWStackSweepPlan script content."""

    def test_idle_script_checks_instances(self):
        """Idle check script should query instance information."""
        from plans.user_ngfw_stack_sweep import UserNGFWStackSweepPlan

        plan = UserNGFWStackSweepPlan()
        idle_step = next(s for s in plan.steps if "idle" in s.name.lower() or "check" in s.name.lower())

        # Should reference instance checking
        assert "instance" in idle_step.script.lower() or "INSTANCE" in idle_step.script

    def test_idle_script_has_threshold(self):
        """Idle check script should use idle threshold."""
        from plans.user_ngfw_stack_sweep import UserNGFWStackSweepPlan

        plan = UserNGFWStackSweepPlan()
        idle_step = next(s for s in plan.steps if "idle" in s.name.lower() or "check" in s.name.lower())

        # Should reference threshold
        assert "threshold" in idle_step.script.lower() or "THRESHOLD" in idle_step.script


class TestUserNGFWStackSweepPlanContext:
    """Test UserNGFWStackSweepPlan.get_context method."""

    def test_get_context_returns_idle_threshold(self):
        """get_context should return idle_threshold_minutes."""
        from plans.user_ngfw_stack_sweep import UserNGFWStackSweepPlan

        plan = UserNGFWStackSweepPlan()
        instance = MockSweepInstance(idle_threshold_minutes=120)
        context = plan.get_context(instance)

        assert "idle_threshold_minutes" in context
        assert context["idle_threshold_minutes"] == 120

    def test_get_context_returns_ngfw_instances(self):
        """get_context should return ngfw_instances."""
        from plans.user_ngfw_stack_sweep import UserNGFWStackSweepPlan

        plan = UserNGFWStackSweepPlan()
        instance = MockSweepInstance()
        context = plan.get_context(instance)

        assert "ngfw_instances" in context

    def test_get_context_missing_ngfw_instances_raises(self):
        """get_context should raise if ngfw_instances is missing."""
        from plans.user_ngfw_stack_sweep import UserNGFWStackSweepPlan

        plan = UserNGFWStackSweepPlan()
        instance = MockSweepInstance()
        instance.ngfw_instances = None

        with pytest.raises(ValueError, match="ngfw_instances"):
            plan.get_context(instance)


class TestUserNGFWStackSweepPlanInterface:
    """Test UserNGFWStackSweepPlan interface compliance."""

    def test_has_steps_attribute(self):
        """UserNGFWStackSweepPlan should have steps attribute."""
        from plans.user_ngfw_stack_sweep import UserNGFWStackSweepPlan

        plan = UserNGFWStackSweepPlan()
        assert hasattr(plan, "steps")
        assert isinstance(plan.steps, list)

    def test_has_verify_step_attribute(self):
        """UserNGFWStackSweepPlan should have verify_step attribute."""
        from plans.user_ngfw_stack_sweep import UserNGFWStackSweepPlan

        plan = UserNGFWStackSweepPlan()
        assert hasattr(plan, "verify_step")

    def test_has_get_context_method(self):
        """UserNGFWStackSweepPlan should have get_context method."""
        from plans.user_ngfw_stack_sweep import UserNGFWStackSweepPlan

        plan = UserNGFWStackSweepPlan()
        assert hasattr(plan, "get_context")
        assert callable(plan.get_context)
