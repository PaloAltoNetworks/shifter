"""Tests for NGFWDeprovisionPlan - TDD: Write tests first, all must fail initially.

NGFWDeprovisionPlan handles NGFW cleanup before Pulumi destroy:
- License deactivation (request license deactivate VM-Capacity mode auto)
- Cleanup verification
"""

from dataclasses import dataclass
from typing import Optional

import pytest


@dataclass
class MockNGFWInstance:
    """Mock NGFW instance for testing get_context."""

    management_ip: str = "10.1.1.50"
    instance_id: str = "i-12345"


class TestNGFWDeprovisionPlanSteps:
    """Test NGFWDeprovisionPlan step definitions."""

    def test_has_expected_steps(self):
        """NGFWDeprovisionPlan should have license deactivation step."""
        from plans.ngfw_deprovision import NGFWDeprovisionPlan

        plan = NGFWDeprovisionPlan()
        assert len(plan.steps) >= 1

    def test_has_license_deactivation_step(self):
        """Plan should include license deactivation step."""
        from plans.ngfw_deprovision import NGFWDeprovisionPlan

        plan = NGFWDeprovisionPlan()
        step_names = [s.name for s in plan.steps]
        assert any("license" in name.lower() for name in step_names)

    def test_license_step_has_timeout(self):
        """License deactivation step needs adequate timeout."""
        from plans.ngfw_deprovision import NGFWDeprovisionPlan

        plan = NGFWDeprovisionPlan()
        license_step = next(s for s in plan.steps if "license" in s.name.lower())
        assert license_step.timeout_seconds >= 300  # At least 5 min

    def test_all_steps_have_names(self):
        """All steps must have names."""
        from plans.ngfw_deprovision import NGFWDeprovisionPlan

        plan = NGFWDeprovisionPlan()
        for step in plan.steps:
            assert step.name, "Step must have a name"

    def test_all_steps_have_scripts(self):
        """All steps must have script content."""
        from plans.ngfw_deprovision import NGFWDeprovisionPlan

        plan = NGFWDeprovisionPlan()
        for step in plan.steps:
            assert step.script, f"Step {step.name} must have a script"


class TestNGFWDeprovisionPlanScripts:
    """Test NGFWDeprovisionPlan script content."""

    def test_license_script_deactivates_vm_capacity(self):
        """License script should use VM-Capacity deactivation command."""
        from plans.ngfw_deprovision import NGFWDeprovisionPlan

        plan = NGFWDeprovisionPlan()
        license_step = next(s for s in plan.steps if "license" in s.name.lower())

        # Validated PAN-OS CLI command
        assert "license deactivate" in license_step.script.lower()
        assert "vm-capacity" in license_step.script.lower()

    def test_license_script_uses_auto_mode(self):
        """License deactivation should use auto mode."""
        from plans.ngfw_deprovision import NGFWDeprovisionPlan

        plan = NGFWDeprovisionPlan()
        license_step = next(s for s in plan.steps if "license" in s.name.lower())

        assert "mode auto" in license_step.script.lower()


class TestNGFWDeprovisionPlanContext:
    """Test NGFWDeprovisionPlan.get_context method."""

    def test_get_context_returns_management_ip(self):
        """get_context should return management_ip."""
        from plans.ngfw_deprovision import NGFWDeprovisionPlan

        plan = NGFWDeprovisionPlan()
        instance = MockNGFWInstance(management_ip="10.1.1.100")
        context = plan.get_context(instance)

        assert "management_ip" in context
        assert context["management_ip"] == "10.1.1.100"

    def test_get_context_missing_management_ip_raises(self):
        """get_context should raise if management_ip is missing."""
        from plans.ngfw_deprovision import NGFWDeprovisionPlan

        plan = NGFWDeprovisionPlan()
        instance = MockNGFWInstance()
        instance.management_ip = None

        with pytest.raises(ValueError, match="management_ip"):
            plan.get_context(instance)


class TestNGFWDeprovisionPlanInterface:
    """Test NGFWDeprovisionPlan interface compliance."""

    def test_has_steps_attribute(self):
        """NGFWDeprovisionPlan should have steps attribute."""
        from plans.ngfw_deprovision import NGFWDeprovisionPlan

        plan = NGFWDeprovisionPlan()
        assert hasattr(plan, "steps")
        assert isinstance(plan.steps, list)

    def test_has_verify_step_attribute(self):
        """NGFWDeprovisionPlan should have verify_step attribute."""
        from plans.ngfw_deprovision import NGFWDeprovisionPlan

        plan = NGFWDeprovisionPlan()
        assert hasattr(plan, "verify_step")

    def test_has_get_context_method(self):
        """NGFWDeprovisionPlan should have get_context method."""
        from plans.ngfw_deprovision import NGFWDeprovisionPlan

        plan = NGFWDeprovisionPlan()
        assert hasattr(plan, "get_context")
        assert callable(plan.get_context)
