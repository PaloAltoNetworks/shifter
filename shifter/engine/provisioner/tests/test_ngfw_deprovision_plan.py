"""Tests for NGFWDeprovisionPlan.

NGFWDeprovisionPlan handles NGFW cleanup before Pulumi destroy:
- License deactivation (request license deactivate VM-Capacity mode auto)
"""

from dataclasses import dataclass

import pytest

from plans.ngfw_deprovision import NGFWDeprovisionPlan


@dataclass
class MockNGFWInstance:
    """Mock NGFW instance for testing get_context."""

    management_ip: str = "10.1.1.50"
    instance_id: str = "i-12345"


class TestNGFWDeprovisionPlan:
    """Tests for NGFWDeprovisionPlan behavior."""

    def test_has_license_deactivation_step(self):
        """Plan has license deactivation step."""
        plan = NGFWDeprovisionPlan()
        step_names = [s.name for s in plan.steps]
        assert any("license" in name.lower() for name in step_names)

    def test_license_script_uses_correct_command(self):
        """License script uses VM-Capacity deactivation with auto mode."""
        plan = NGFWDeprovisionPlan()
        license_step = next(s for s in plan.steps if "license" in s.name.lower())
        script = license_step.script.lower()

        assert "license deactivate" in script
        assert "vm-capacity" in script
        assert "mode auto" in script


class TestNGFWDeprovisionPlanContext:
    """Tests for get_context method."""

    def test_get_context_returns_management_ip(self):
        """get_context returns management_ip."""
        plan = NGFWDeprovisionPlan()
        instance = MockNGFWInstance(management_ip="10.1.1.100")
        context = plan.get_context(instance)

        assert context["management_ip"] == "10.1.1.100"

    def test_get_context_missing_management_ip_raises(self):
        """get_context raises if management_ip is missing."""
        plan = NGFWDeprovisionPlan()
        instance = MockNGFWInstance()
        instance.management_ip = None

        with pytest.raises(ValueError, match="management_ip"):
            plan.get_context(instance)
