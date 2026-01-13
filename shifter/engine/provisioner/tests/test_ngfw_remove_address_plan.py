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


class TestNGFWRemoveAddressPlanSteps:
    """Test NGFWRemoveAddressPlan step definitions."""

    def test_has_one_step(self):
        """NGFWRemoveAddressPlan should have 1 step."""
        from plans.ngfw_remove_address import NGFWRemoveAddressPlan

        plan = NGFWRemoveAddressPlan()
        assert len(plan.steps) == 1

    def test_step_name_is_remove_address(self):
        """Step should be named remove_address."""
        from plans.ngfw_remove_address import NGFWRemoveAddressPlan

        plan = NGFWRemoveAddressPlan()
        assert plan.steps[0].name == "remove_address"

    def test_step_has_stdin_input(self):
        """Step must use stdin_input for PAN-OS configure mode."""
        from plans.ngfw_remove_address import NGFWRemoveAddressPlan

        plan = NGFWRemoveAddressPlan()
        assert plan.steps[0].stdin_input, "Step must have stdin_input"

    def test_step_has_timeout(self):
        """Step must have positive timeout."""
        from plans.ngfw_remove_address import NGFWRemoveAddressPlan

        plan = NGFWRemoveAddressPlan()
        assert plan.steps[0].timeout_seconds > 0


class TestNGFWRemoveAddressPlanVerification:
    """Test NGFWRemoveAddressPlan verification step."""

    def test_has_verification_step(self):
        """NGFWRemoveAddressPlan should have a verification step."""
        from plans.ngfw_remove_address import NGFWRemoveAddressPlan

        plan = NGFWRemoveAddressPlan()
        assert plan.verify_step is not None

    def test_verification_step_is_marked_as_verification(self):
        """Verification step should have is_verification=True."""
        from plans.ngfw_remove_address import NGFWRemoveAddressPlan

        plan = NGFWRemoveAddressPlan()
        assert plan.verify_step.is_verification is True


class TestNGFWRemoveAddressPlanContext:
    """Test NGFWRemoveAddressPlan.get_context method."""

    def test_get_context_returns_name(self):
        """get_context should return name."""
        from plans.ngfw_remove_address import NGFWRemoveAddressPlan

        plan = NGFWRemoveAddressPlan()
        config = MockAddressConfig(name="servers-subnet")
        context = plan.get_context(config)

        assert "name" in context
        assert context["name"] == "servers-subnet"

    def test_get_context_returns_management_ip(self):
        """get_context should return management_ip."""
        from plans.ngfw_remove_address import NGFWRemoveAddressPlan

        plan = NGFWRemoveAddressPlan()
        config = MockAddressConfig(management_ip="10.0.4.50")
        context = plan.get_context(config)

        assert "management_ip" in context
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

    def test_stdin_input_deletes_address(self):
        """stdin_input should delete address object."""
        from plans.ngfw_remove_address import NGFWRemoveAddressPlan

        plan = NGFWRemoveAddressPlan()
        content = plan.steps[0].stdin_input

        assert "delete address" in content

    def test_stdin_input_has_name_template(self):
        """stdin_input should have {{ name }} template variable."""
        from plans.ngfw_remove_address import NGFWRemoveAddressPlan

        plan = NGFWRemoveAddressPlan()
        content = plan.steps[0].stdin_input

        assert "{{ name }}" in content

    def test_stdin_input_includes_commit(self):
        """stdin_input must include commit command."""
        from plans.ngfw_remove_address import NGFWRemoveAddressPlan

        plan = NGFWRemoveAddressPlan()
        content = plan.steps[0].stdin_input

        assert "commit" in content.lower()

    def test_stdin_input_enters_configure_mode(self):
        """stdin_input must enter configure mode."""
        from plans.ngfw_remove_address import NGFWRemoveAddressPlan

        plan = NGFWRemoveAddressPlan()
        content = plan.steps[0].stdin_input

        assert "configure" in content.lower()


class TestNGFWRemoveAddressPlanInterface:
    """Test NGFWRemoveAddressPlan interface compliance."""

    def test_has_steps_attribute(self):
        """NGFWRemoveAddressPlan should have steps attribute."""
        from plans.ngfw_remove_address import NGFWRemoveAddressPlan

        plan = NGFWRemoveAddressPlan()
        assert hasattr(plan, "steps")
        assert isinstance(plan.steps, list)

    def test_has_verify_step_attribute(self):
        """NGFWRemoveAddressPlan should have verify_step attribute."""
        from plans.ngfw_remove_address import NGFWRemoveAddressPlan

        plan = NGFWRemoveAddressPlan()
        assert hasattr(plan, "verify_step")

    def test_has_get_context_method(self):
        """NGFWRemoveAddressPlan should have get_context method."""
        from plans.ngfw_remove_address import NGFWRemoveAddressPlan

        plan = NGFWRemoveAddressPlan()
        assert hasattr(plan, "get_context")
        assert callable(plan.get_context)

    def test_has_name_attribute(self):
        """NGFWRemoveAddressPlan should have name attribute."""
        from plans.ngfw_remove_address import NGFWRemoveAddressPlan

        plan = NGFWRemoveAddressPlan()
        assert hasattr(plan, "name")
        assert plan.name == "ngfw_remove_address"
