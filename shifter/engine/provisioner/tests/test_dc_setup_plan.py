"""Tests for DCSetupPlan.

DCSetupPlan defines the specific steps to promote a Windows Server
(with AD DS feature prebaked in AMI) to a Domain Controller.
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

    def test_has_promote_step(self):
        """Plan has promote_to_dc step."""
        plan = DCSetupPlan()
        step_names = [step.name for step in plan.steps]
        assert "promote_to_dc" in step_names

    def test_promote_step_requires_reboot(self):
        """Promote step requires reboot (DC restarts after promotion)."""
        plan = DCSetupPlan()
        promote_step = next(s for s in plan.steps if s.name == "promote_to_dc")
        assert promote_step.requires_reboot is True

    def test_single_reboot_with_prebaked_ami(self):
        """With prebaked AMI, DC setup only needs 1 reboot (promote only)."""
        plan = DCSetupPlan()
        reboot_steps = [s for s in plan.steps if s.requires_reboot]
        assert len(reboot_steps) == 1
        assert reboot_steps[0].name == "promote_to_dc"

    def test_promote_script_uses_install_addsforest(self):
        """Promote script uses Install-ADDSForest cmdlet."""
        plan = DCSetupPlan()
        promote_step = next(s for s in plan.steps if s.name == "promote_to_dc")
        assert "Install-ADDSForest" in promote_step.script

    def test_promote_script_uses_template_variables(self):
        """Promote script uses template variables for config."""
        plan = DCSetupPlan()
        promote_step = next(s for s in plan.steps if s.name == "promote_to_dc")
        script = promote_step.script
        assert "{{ domain_name }}" in script or "{{domain_name}}" in script
        assert "{{ netbios_name }}" in script or "{{netbios_name}}" in script

    def test_passwords_use_securestring(self):
        """Passwords are converted to SecureString in PowerShell."""
        plan = DCSetupPlan()
        promote_step = next(s for s in plan.steps if s.name == "promote_to_dc")
        assert "ConvertTo-SecureString" in promote_step.script


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
