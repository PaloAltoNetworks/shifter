"""Tests for NGFWStartPlan - TDD: Write tests first, all must fail initially.

NGFWStartPlan handles starting a stopped NGFW instance:
- Start EC2 instance
- Wait for running state
- Wait for SSH availability
"""

from dataclasses import dataclass
from typing import Optional

import pytest


@dataclass
class MockNGFWInstance:
    """Mock NGFW instance for testing get_context."""

    instance_id: str = "i-12345"
    management_ip: str = "10.1.1.50"


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

    def test_has_ssh_ready_step(self):
        """Plan should include SSH ready verification step."""
        from plans.ngfw_start import NGFWStartPlan

        plan = NGFWStartPlan()
        step_names = [s.name for s in plan.steps]
        assert any("ssh" in name.lower() for name in step_names)

    def test_start_before_wait(self):
        """Start must come before wait steps."""
        from plans.ngfw_start import NGFWStartPlan

        plan = NGFWStartPlan()
        step_names = [s.name for s in plan.steps]

        start_idx = next(i for i, n in enumerate(step_names) if "start" in n.lower())
        # Find any wait/running step
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

    def test_all_steps_have_scripts(self):
        """All steps must have script content."""
        from plans.ngfw_start import NGFWStartPlan

        plan = NGFWStartPlan()
        for step in plan.steps:
            assert step.script, f"Step {step.name} must have a script"

    def test_all_steps_have_timeouts(self):
        """All steps must have positive timeouts."""
        from plans.ngfw_start import NGFWStartPlan

        plan = NGFWStartPlan()
        for step in plan.steps:
            assert step.timeout_seconds > 0

    def test_ssh_wait_has_adequate_timeout(self):
        """SSH wait step needs adequate timeout (~3 min for warm start)."""
        from plans.ngfw_start import NGFWStartPlan

        plan = NGFWStartPlan()
        ssh_step = next(s for s in plan.steps if "ssh" in s.name.lower())
        assert ssh_step.timeout_seconds >= 180  # At least 3 min


class TestNGFWStartPlanScripts:
    """Test NGFWStartPlan script content."""

    def test_start_script_uses_aws_cli(self):
        """Start script should use AWS CLI for EC2 start."""
        from plans.ngfw_start import NGFWStartPlan

        plan = NGFWStartPlan()
        start_step = next(s for s in plan.steps if "start" in s.name.lower() and "ssh" not in s.name.lower())

        assert "aws" in start_step.script.lower()
        assert "start-instances" in start_step.script.lower()

    def test_start_script_includes_instance_id(self):
        """Start script should reference instance ID."""
        from plans.ngfw_start import NGFWStartPlan

        plan = NGFWStartPlan()
        start_step = next(s for s in plan.steps if "start" in s.name.lower() and "ssh" not in s.name.lower())

        assert "instance_id" in start_step.script or "INSTANCE_ID" in start_step.script

    def test_wait_script_checks_state(self):
        """Wait script should check instance state."""
        from plans.ngfw_start import NGFWStartPlan

        plan = NGFWStartPlan()
        wait_step = next(
            s for s in plan.steps
            if "running" in s.name.lower() or ("wait" in s.name.lower() and "ssh" not in s.name.lower())
        )

        assert "describe-instances" in wait_step.script or "instance-running" in wait_step.script

    def test_ssh_script_checks_connectivity(self):
        """SSH ready script should verify SSH connectivity."""
        from plans.ngfw_start import NGFWStartPlan

        plan = NGFWStartPlan()
        ssh_step = next(s for s in plan.steps if "ssh" in s.name.lower())

        assert "ssh" in ssh_step.script.lower()


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

    def test_get_context_returns_management_ip(self):
        """get_context should return management_ip for SSH check."""
        from plans.ngfw_start import NGFWStartPlan

        plan = NGFWStartPlan()
        instance = MockNGFWInstance(management_ip="10.2.2.100")
        context = plan.get_context(instance)

        assert "management_ip" in context
        assert context["management_ip"] == "10.2.2.100"

    def test_get_context_missing_instance_id_raises(self):
        """get_context should raise if instance_id is missing."""
        from plans.ngfw_start import NGFWStartPlan

        plan = NGFWStartPlan()
        instance = MockNGFWInstance()
        instance.instance_id = None

        with pytest.raises(ValueError, match="instance_id"):
            plan.get_context(instance)

    def test_get_context_missing_management_ip_raises(self):
        """get_context should raise if management_ip is missing."""
        from plans.ngfw_start import NGFWStartPlan

        plan = NGFWStartPlan()
        instance = MockNGFWInstance()
        instance.management_ip = None

        with pytest.raises(ValueError, match="management_ip"):
            plan.get_context(instance)


class TestNGFWStartPlanInterface:
    """Test NGFWStartPlan interface compliance."""

    def test_has_steps_attribute(self):
        """NGFWStartPlan should have steps attribute."""
        from plans.ngfw_start import NGFWStartPlan

        plan = NGFWStartPlan()
        assert hasattr(plan, "steps")
        assert isinstance(plan.steps, list)

    def test_has_verify_step_attribute(self):
        """NGFWStartPlan should have verify_step attribute."""
        from plans.ngfw_start import NGFWStartPlan

        plan = NGFWStartPlan()
        assert hasattr(plan, "verify_step")

    def test_has_get_context_method(self):
        """NGFWStartPlan should have get_context method."""
        from plans.ngfw_start import NGFWStartPlan

        plan = NGFWStartPlan()
        assert hasattr(plan, "get_context")
        assert callable(plan.get_context)
