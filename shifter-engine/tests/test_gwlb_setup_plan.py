"""Tests for GWLBSetupPlan - TDD: Write tests first, all must fail initially.

GWLBSetupPlan handles GWLB target registration after NGFW provisioning:
- Register NGFW data ENI as target
- Verify target health check
"""

from dataclasses import dataclass
from typing import Optional

import pytest


@dataclass
class MockGWLBInstance:
    """Mock GWLB instance for testing get_context."""

    target_group_arn: str = "arn:aws:elasticloadbalancing:us-east-2:123456789012:targetgroup/test"
    ngfw_data_eni_id: str = "eni-12345"
    ngfw_instance_id: str = "i-12345"


class TestGWLBSetupPlanSteps:
    """Test GWLBSetupPlan step definitions."""

    def test_has_expected_steps(self):
        """GWLBSetupPlan should have target registration and health check steps."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        assert len(plan.steps) >= 2

    def test_has_register_target_step(self):
        """Plan should include target registration step."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        step_names = [s.name for s in plan.steps]
        assert any("register" in name.lower() for name in step_names)

    def test_has_health_check_step(self):
        """Plan should include health check verification step."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        step_names = [s.name for s in plan.steps]
        assert any("health" in name.lower() for name in step_names)

    def test_register_before_health_check(self):
        """Target registration must come before health check."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        step_names = [s.name for s in plan.steps]

        register_idx = next(i for i, n in enumerate(step_names) if "register" in n.lower())
        health_idx = next(i for i, n in enumerate(step_names) if "health" in n.lower())
        assert register_idx < health_idx

    def test_all_steps_have_names(self):
        """All steps must have names."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        for step in plan.steps:
            assert step.name, "Step must have a name"

    def test_all_steps_have_scripts(self):
        """All steps must have script content."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        for step in plan.steps:
            assert step.script, f"Step {step.name} must have a script"

    def test_all_steps_have_timeouts(self):
        """All steps must have positive timeouts."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        for step in plan.steps:
            assert step.timeout_seconds > 0


class TestGWLBSetupPlanScripts:
    """Test GWLBSetupPlan script content."""

    def test_register_script_uses_aws_cli(self):
        """Register script should use AWS CLI for target registration."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        register_step = next(s for s in plan.steps if "register" in s.name.lower())

        # Should use AWS CLI elbv2 command
        assert "aws" in register_step.script.lower()
        assert "register-targets" in register_step.script.lower()

    def test_register_script_includes_target_group_arn(self):
        """Register script should reference target group ARN."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        register_step = next(s for s in plan.steps if "register" in s.name.lower())

        assert "target_group_arn" in register_step.script or "target-group-arn" in register_step.script

    def test_health_check_script_verifies_status(self):
        """Health check script should verify target health status."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        health_step = next(s for s in plan.steps if "health" in s.name.lower())

        # Should check target health
        assert "describe-target-health" in health_step.script or "health" in health_step.script.lower()


class TestGWLBSetupPlanContext:
    """Test GWLBSetupPlan.get_context method."""

    def test_get_context_returns_target_group_arn(self):
        """get_context should return target_group_arn."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        instance = MockGWLBInstance(target_group_arn="arn:aws:test")
        context = plan.get_context(instance)

        assert "target_group_arn" in context
        assert context["target_group_arn"] == "arn:aws:test"

    def test_get_context_returns_target_id(self):
        """get_context should return target ID (ENI or instance)."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        instance = MockGWLBInstance(ngfw_instance_id="i-99999")
        context = plan.get_context(instance)

        # Should return either ngfw_instance_id or ngfw_data_eni_id
        assert "target_id" in context or "ngfw_instance_id" in context

    def test_get_context_missing_target_group_raises(self):
        """get_context should raise if target_group_arn is missing."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        instance = MockGWLBInstance()
        instance.target_group_arn = None

        with pytest.raises(ValueError, match="target_group"):
            plan.get_context(instance)


class TestGWLBSetupPlanInterface:
    """Test GWLBSetupPlan interface compliance."""

    def test_has_steps_attribute(self):
        """GWLBSetupPlan should have steps attribute."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        assert hasattr(plan, "steps")
        assert isinstance(plan.steps, list)

    def test_has_verify_step_attribute(self):
        """GWLBSetupPlan should have verify_step attribute."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        assert hasattr(plan, "verify_step")

    def test_has_get_context_method(self):
        """GWLBSetupPlan should have get_context method."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        assert hasattr(plan, "get_context")
        assert callable(plan.get_context)
