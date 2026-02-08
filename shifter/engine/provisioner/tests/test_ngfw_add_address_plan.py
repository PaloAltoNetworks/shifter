"""Tests for NGFWAddAddressPlan.

NGFWAddAddressPlan creates a PAN-OS address object representing a subnet CIDR.
Used by CMS to configure routing policies between logical subnets.
"""

from dataclasses import dataclass

import pytest


@dataclass
class MockAddressConfig:
    """Mock config for testing get_context."""

    name: str = "dc-subnet"
    cidr: str = "10.1.1.0/24"
    management_ip: str = "10.0.4.10"


class TestNGFWAddAddressPlanStructure:
    """Test NGFWAddAddressPlan step definitions and verification."""

    def test_plan_structure(self):
        """Plan should have 1 step with stdin_input and a verification step."""
        from plans.ngfw_add_address import NGFWAddAddressPlan

        plan = NGFWAddAddressPlan()

        # Main step
        assert len(plan.steps) == 1
        assert plan.steps[0].name == "add_address"
        assert plan.steps[0].stdin_input, "Step must have stdin_input for PAN-OS configure mode"
        assert plan.steps[0].timeout_seconds > 0

        # Verification
        assert plan.verify_step is not None
        assert plan.verify_step.is_verification is True


class TestNGFWAddAddressPlanContext:
    """Test NGFWAddAddressPlan.get_context method."""

    def test_get_context_returns_all_fields(self):
        """get_context should return name, cidr, and management_ip."""
        from plans.ngfw_add_address import NGFWAddAddressPlan

        plan = NGFWAddAddressPlan()
        config = MockAddressConfig(
            name="servers-subnet",
            cidr="10.2.0.0/16",
            management_ip="10.0.4.50",
        )
        context = plan.get_context(config)

        assert context["name"] == "servers-subnet"
        assert context["cidr"] == "10.2.0.0/16"
        assert context["management_ip"] == "10.0.4.50"

    def test_get_context_missing_name_raises(self):
        """get_context should raise if name is missing."""
        from plans.ngfw_add_address import NGFWAddAddressPlan

        plan = NGFWAddAddressPlan()
        config = MockAddressConfig()
        config.name = None

        with pytest.raises(ValueError, match="name"):
            plan.get_context(config)

    def test_get_context_missing_cidr_raises(self):
        """get_context should raise if cidr is missing."""
        from plans.ngfw_add_address import NGFWAddAddressPlan

        plan = NGFWAddAddressPlan()
        config = MockAddressConfig()
        config.cidr = None

        with pytest.raises(ValueError, match="cidr"):
            plan.get_context(config)

    def test_get_context_missing_management_ip_raises(self):
        """get_context should raise if management_ip is missing."""
        from plans.ngfw_add_address import NGFWAddAddressPlan

        plan = NGFWAddAddressPlan()
        config = MockAddressConfig()
        config.management_ip = None

        with pytest.raises(ValueError, match="management_ip"):
            plan.get_context(config)


class TestNGFWAddAddressPlanScripts:
    """Test NGFWAddAddressPlan script content."""

    def test_stdin_input_has_required_commands(self):
        """stdin_input should have configure mode, set address, templates, and commit."""
        from plans.ngfw_add_address import NGFWAddAddressPlan

        plan = NGFWAddAddressPlan()
        content = plan.steps[0].stdin_input

        # Must enter configure mode
        assert "configure" in content.lower()
        # Must set address with ip-netmask
        assert "set address" in content
        assert "ip-netmask" in content
        # Must have template variables
        assert "{{ name }}" in content
        assert "{{ cidr }}" in content
        # Must commit changes
        assert "commit" in content.lower()
