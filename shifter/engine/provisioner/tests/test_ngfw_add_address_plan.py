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


class TestNGFWAddAddressPlanSteps:
    """Test NGFWAddAddressPlan step definitions."""

    def test_has_one_step(self):
        """NGFWAddAddressPlan should have 1 step."""
        from plans.ngfw_add_address import NGFWAddAddressPlan

        plan = NGFWAddAddressPlan()
        assert len(plan.steps) == 1

    def test_step_name_is_add_address(self):
        """Step should be named add_address."""
        from plans.ngfw_add_address import NGFWAddAddressPlan

        plan = NGFWAddAddressPlan()
        assert plan.steps[0].name == "add_address"

    def test_step_has_stdin_input(self):
        """Step must use stdin_input for PAN-OS configure mode."""
        from plans.ngfw_add_address import NGFWAddAddressPlan

        plan = NGFWAddAddressPlan()
        assert plan.steps[0].stdin_input, "Step must have stdin_input"

    def test_step_has_timeout(self):
        """Step must have positive timeout."""
        from plans.ngfw_add_address import NGFWAddAddressPlan

        plan = NGFWAddAddressPlan()
        assert plan.steps[0].timeout_seconds > 0


class TestNGFWAddAddressPlanVerification:
    """Test NGFWAddAddressPlan verification step."""

    def test_has_verification_step(self):
        """NGFWAddAddressPlan should have a verification step."""
        from plans.ngfw_add_address import NGFWAddAddressPlan

        plan = NGFWAddAddressPlan()
        assert plan.verify_step is not None

    def test_verification_step_is_marked_as_verification(self):
        """Verification step should have is_verification=True."""
        from plans.ngfw_add_address import NGFWAddAddressPlan

        plan = NGFWAddAddressPlan()
        assert plan.verify_step.is_verification is True


class TestNGFWAddAddressPlanContext:
    """Test NGFWAddAddressPlan.get_context method."""

    def test_get_context_returns_name(self):
        """get_context should return name."""
        from plans.ngfw_add_address import NGFWAddAddressPlan

        plan = NGFWAddAddressPlan()
        config = MockAddressConfig(name="servers-subnet")
        context = plan.get_context(config)

        assert "name" in context
        assert context["name"] == "servers-subnet"

    def test_get_context_returns_cidr(self):
        """get_context should return cidr."""
        from plans.ngfw_add_address import NGFWAddAddressPlan

        plan = NGFWAddAddressPlan()
        config = MockAddressConfig(cidr="10.2.0.0/16")
        context = plan.get_context(config)

        assert "cidr" in context
        assert context["cidr"] == "10.2.0.0/16"

    def test_get_context_returns_management_ip(self):
        """get_context should return management_ip."""
        from plans.ngfw_add_address import NGFWAddAddressPlan

        plan = NGFWAddAddressPlan()
        config = MockAddressConfig(management_ip="10.0.4.50")
        context = plan.get_context(config)

        assert "management_ip" in context
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

    def test_stdin_input_sets_address(self):
        """stdin_input should set address object."""
        from plans.ngfw_add_address import NGFWAddAddressPlan

        plan = NGFWAddAddressPlan()
        content = plan.steps[0].stdin_input

        assert "set address" in content
        assert "ip-netmask" in content

    def test_stdin_input_has_name_template(self):
        """stdin_input should have {{ name }} template variable."""
        from plans.ngfw_add_address import NGFWAddAddressPlan

        plan = NGFWAddAddressPlan()
        content = plan.steps[0].stdin_input

        assert "{{ name }}" in content

    def test_stdin_input_has_cidr_template(self):
        """stdin_input should have {{ cidr }} template variable."""
        from plans.ngfw_add_address import NGFWAddAddressPlan

        plan = NGFWAddAddressPlan()
        content = plan.steps[0].stdin_input

        assert "{{ cidr }}" in content

    def test_stdin_input_includes_commit(self):
        """stdin_input must include commit command."""
        from plans.ngfw_add_address import NGFWAddAddressPlan

        plan = NGFWAddAddressPlan()
        content = plan.steps[0].stdin_input

        assert "commit" in content.lower()

    def test_stdin_input_enters_configure_mode(self):
        """stdin_input must enter configure mode."""
        from plans.ngfw_add_address import NGFWAddAddressPlan

        plan = NGFWAddAddressPlan()
        content = plan.steps[0].stdin_input

        assert "configure" in content.lower()


class TestNGFWAddAddressPlanInterface:
    """Test NGFWAddAddressPlan interface compliance."""

    def test_has_steps_attribute(self):
        """NGFWAddAddressPlan should have steps attribute."""
        from plans.ngfw_add_address import NGFWAddAddressPlan

        plan = NGFWAddAddressPlan()
        assert hasattr(plan, "steps")
        assert isinstance(plan.steps, list)

    def test_has_verify_step_attribute(self):
        """NGFWAddAddressPlan should have verify_step attribute."""
        from plans.ngfw_add_address import NGFWAddAddressPlan

        plan = NGFWAddAddressPlan()
        assert hasattr(plan, "verify_step")

    def test_has_get_context_method(self):
        """NGFWAddAddressPlan should have get_context method."""
        from plans.ngfw_add_address import NGFWAddAddressPlan

        plan = NGFWAddAddressPlan()
        assert hasattr(plan, "get_context")
        assert callable(plan.get_context)

    def test_has_name_attribute(self):
        """NGFWAddAddressPlan should have name attribute."""
        from plans.ngfw_add_address import NGFWAddAddressPlan

        plan = NGFWAddAddressPlan()
        assert hasattr(plan, "name")
        assert plan.name == "ngfw_add_address"
