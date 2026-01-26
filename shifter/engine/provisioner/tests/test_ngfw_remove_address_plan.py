"""Tests for NGFWRemoveAddressPlan.

NGFWRemoveAddressPlan deletes a PAN-OS address object.
Used by CMS when tearing down routing policies.
"""

from dataclasses import dataclass

import pytest


@dataclass
class MockAddressConfig:
    """Mock config for testing get_context."""

    name: str = "dc-subnet"
    management_ip: str = "10.0.4.10"


class TestNGFWRemoveAddressPlanStructure:
    """Test NGFWRemoveAddressPlan step definitions and verification."""

    def test_plan_structure(self):
        """Plan should have 1 step with stdin_input and a verification step."""
        from plans.ngfw_remove_address import NGFWRemoveAddressPlan

        plan = NGFWRemoveAddressPlan()

        # Main step
        assert len(plan.steps) == 1
        assert plan.steps[0].name == "remove_address"
        assert plan.steps[0].stdin_input, "Step must have stdin_input for PAN-OS configure mode"
        assert plan.steps[0].timeout_seconds > 0

        # Verification
        assert plan.verify_step is not None
        assert plan.verify_step.is_verification is True


class TestNGFWRemoveAddressPlanContext:
    """Test NGFWRemoveAddressPlan.get_context method."""

    def test_get_context_returns_all_fields(self):
        """get_context should return name and management_ip."""
        from plans.ngfw_remove_address import NGFWRemoveAddressPlan

        plan = NGFWRemoveAddressPlan()
        config = MockAddressConfig(name="servers-subnet", management_ip="10.0.4.50")
        context = plan.get_context(config)

        assert context["name"] == "servers-subnet"
        assert context["management_ip"] == "10.0.4.50"

    def test_get_context_missing_name_raises(self):
        """get_context should raise if name is missing."""
        from plans.ngfw_remove_address import NGFWRemoveAddressPlan

        plan = NGFWRemoveAddressPlan()
        config = MockAddressConfig()
        config.name = None

        with pytest.raises(ValueError, match="name"):
            plan.get_context(config)

    def test_get_context_missing_management_ip_raises(self):
        """get_context should raise if management_ip is missing."""
        from plans.ngfw_remove_address import NGFWRemoveAddressPlan

        plan = NGFWRemoveAddressPlan()
        config = MockAddressConfig()
        config.management_ip = None

        with pytest.raises(ValueError, match="management_ip"):
            plan.get_context(config)


class TestNGFWRemoveAddressPlanScripts:
    """Test NGFWRemoveAddressPlan script content."""

    def test_stdin_input_has_required_commands(self):
        """stdin_input should have configure mode, delete address, template, and commit."""
        from plans.ngfw_remove_address import NGFWRemoveAddressPlan

        plan = NGFWRemoveAddressPlan()
        content = plan.steps[0].stdin_input

        # Must enter configure mode
        assert "configure" in content.lower()
        # Must delete address
        assert "delete address" in content
        # Must have template variable
        assert "{{ name }}" in content
        # Must commit changes
        assert "commit" in content.lower()
