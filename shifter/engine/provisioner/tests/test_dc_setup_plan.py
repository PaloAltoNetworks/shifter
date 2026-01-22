"""Tests for DCSetupPlan.

DCSetupPlan is used with a prebaked DC AMI where the domain is already
promoted. The plan only verifies the DC is running - no promotion needed.
"""

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from plans.dc_setup import DCSetupPlan


@dataclass
class MockDCInstance:
    """Mock DC instance for testing."""

    domain_name: str = "shifter.local"
    netbios_name: str = "SHIFTER"
    dsrm_password: str = "DsrmPass123!"
    domain_admin_password: str = "AdminPass456!"


class TestDCSetupPlan:
    """Tests for DCSetupPlan behavior."""

    def test_no_setup_steps_with_prebaked_ami(self):
        """Prebaked DC has no setup steps - domain already promoted."""
        plan = DCSetupPlan()
        assert len(plan.steps) == 0

    def test_no_reboots_with_prebaked_ami(self):
        """Prebaked DC has no reboots - domain already promoted."""
        plan = DCSetupPlan()
        reboot_steps = [s for s in plan.steps if s.requires_reboot]
        assert len(reboot_steps) == 0

    def test_has_verify_step(self):
        """Plan has verify_ad_running verification step."""
        plan = DCSetupPlan()
        assert plan.verify_step is not None
        assert plan.verify_step.name == "verify_ad_running"
        assert plan.verify_step.is_verification is True


class TestDCSetupPlanContext:
    """Tests for get_context method."""

    def test_get_context_returns_all_vars(self):
        """get_context returns all required template variables."""
        plan = DCSetupPlan()
        instance = MockDCInstance()
        context = plan.get_context(instance)

        assert context["domain_name"] == "shifter.local"
        assert context["netbios_name"] == "SHIFTER"
        assert context["dsrm_password"] == "DsrmPass123!"
        assert context["domain_admin_password"] == "AdminPass456!"

    def test_get_context_missing_attr_raises(self):
        """Instance missing required attribute raises error."""
        plan = DCSetupPlan()
        incomplete_instance = MagicMock()
        incomplete_instance.domain_name = None
        incomplete_instance.netbios_name = "SHIFTER"
        incomplete_instance.dsrm_password = "pass"
        incomplete_instance.domain_admin_password = "pass"

        with pytest.raises((AttributeError, ValueError, KeyError)):
            plan.get_context(incomplete_instance)
