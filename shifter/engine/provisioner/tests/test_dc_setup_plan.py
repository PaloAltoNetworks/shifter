"""Tests for DCSetupPlan.

DCSetupPlan is used with a prebaked DC AMI where the domain is already
promoted. The plan configures runtime settings and verifies the DC is running.
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
    dsrm_password: str = "DsrmPass123!"  # nosec B105  # NOSONAR — test fixture
    domain_admin_password: str = "AdminPass456!"  # nosec B105  # NOSONAR — test fixture


class TestDCSetupPlan:
    """Tests for DCSetupPlan behavior."""

    def test_has_required_steps(self):
        """Plan has password and SSH config steps."""
        plan = DCSetupPlan()
        assert len(plan.steps) == 2
        assert plan.steps[0].name == "set_admin_password"
        assert plan.steps[1].name == "enable_ssh_password_auth"

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

    def test_runtime_promotion_mode_includes_promotion_step_and_reboot(self):
        """Runtime promotion mode should promote AD before post-setup verification."""
        plan = DCSetupPlan(runtime_promotion=True)

        assert [step.name for step in plan.steps] == [
            "promote_domain_controller",
            "set_admin_password",
            "enable_ssh_password_auth",
        ]
        assert plan.steps[0].requires_reboot is True

    def test_runtime_promotion_script_installs_ad_ds_if_missing(self):
        """Runtime promotion script should install AD DS on a base Windows image."""
        plan = DCSetupPlan(runtime_promotion=True)
        promote_step = plan.steps[0]

        assert "Install-WindowsFeature -Name AD-Domain-Services" in promote_step.script
        assert "Get-ADDomainController" in promote_step.script

    def test_ssh_auth_step_bootstraps_missing_openssh_config(self):
        """SSH auth step should configure a prebaked DC with OpenSSH present."""
        plan = DCSetupPlan()
        ssh_step = plan.steps[1]

        assert ssh_step.timeout_seconds == 600
        assert "Get-Service -Name sshd" in ssh_step.script
        assert "Rebuild and publish a Polaris DC AMI with OpenSSH preinstalled" in ssh_step.script
        assert "Add-WindowsCapability -Online -Name OpenSSH.Server" not in ssh_step.script
        assert "New-Service -Name sshd" in ssh_step.script
        assert "sshd_config_default" in ssh_step.script
        assert "Created minimal sshd_config" in ssh_step.script
        assert 'New-NetFirewallRule -Name "OpenSSH-Server-In-TCP"' in ssh_step.script
        assert "PasswordAuthentication yes" in ssh_step.script


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
