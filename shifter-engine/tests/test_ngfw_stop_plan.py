"""Tests for NGFWStopPlan - TDD: Write tests first, all must fail initially.

NGFWStopPlan handles stopping a running NGFW instance:
- Stop EC2 instance
- Wait for stopped state
"""

from dataclasses import dataclass
from typing import Optional

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

    def test_all_steps_have_scripts(self):
        """All steps must have script content."""
        from plans.ngfw_stop import NGFWStopPlan

        plan = NGFWStopPlan()
        for step in plan.steps:
            assert step.script, f"Step {step.name} must have a script"

    def test_all_steps_have_timeouts(self):
        """All steps must have positive timeouts."""
        from plans.ngfw_stop import NGFWStopPlan

        plan = NGFWStopPlan()
        for step in plan.steps:
            assert step.timeout_seconds > 0


class TestNGFWStopPlanScripts:
    """Test NGFWStopPlan script content."""

    def test_stop_script_uses_aws_cli(self):
        """Stop script should use AWS CLI for EC2 stop."""
        from plans.ngfw_stop import NGFWStopPlan

        plan = NGFWStopPlan()
        stop_step = next(s for s in plan.steps if "stop" in s.name.lower() and "wait" not in s.name.lower())

        assert "aws" in stop_step.script.lower()
        assert "stop-instances" in stop_step.script.lower()

    def test_stop_script_includes_instance_id(self):
        """Stop script should reference instance ID."""
        from plans.ngfw_stop import NGFWStopPlan

        plan = NGFWStopPlan()
        stop_step = next(s for s in plan.steps if "stop" in s.name.lower() and "wait" not in s.name.lower())

        assert "instance_id" in stop_step.script or "INSTANCE_ID" in stop_step.script

    def test_wait_script_checks_state(self):
        """Wait script should check instance state."""
        from plans.ngfw_stop import NGFWStopPlan

        plan = NGFWStopPlan()
        wait_step = next(
            s for s in plan.steps
            if "stopped" in s.name.lower() or "wait" in s.name.lower()
        )

        assert "describe-instances" in wait_step.script or "instance-stopped" in wait_step.script


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

    def test_has_verify_step_attribute(self):
        """NGFWStopPlan should have verify_step attribute."""
        from plans.ngfw_stop import NGFWStopPlan

        plan = NGFWStopPlan()
        assert hasattr(plan, "verify_step")

    def test_has_get_context_method(self):
        """NGFWStopPlan should have get_context method."""
        from plans.ngfw_stop import NGFWStopPlan

        plan = NGFWStopPlan()
        assert hasattr(plan, "get_context")
        assert callable(plan.get_context)
