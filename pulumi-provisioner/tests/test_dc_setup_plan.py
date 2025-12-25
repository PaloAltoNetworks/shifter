"""Tests for DCSetupPlan - TDD: Write tests first, all must fail initially.

DCSetupPlan defines the specific steps to set up a Windows Domain Controller.
"""

from unittest.mock import MagicMock
from dataclasses import dataclass

import pytest

# These imports will fail initially - that's expected for TDD
from components.plans.dc_setup import DCSetupPlan
from components.setup_plan import SetupStep


@dataclass
class MockDCInstance:
    """Mock DC instance for testing."""
    domain_name: str = "shifter.local"
    netbios_name: str = "SHIFTER"
    dsrm_password: str = "DsrmPass123!"
    domain_admin_password: str = "AdminPass456!"
    hostname: str = "shifter-dc-1"
    private_ip: str = "10.1.3.100"


class TestDCSetupPlanSteps:
    """Test DC setup plan step definitions."""

    def test_steps_in_correct_order(self):
        """install_ad_feature must come before promote_to_dc."""
        plan = DCSetupPlan()

        step_names = [step.name for step in plan.steps]

        # install must come before promote
        install_idx = step_names.index("install_ad_feature")
        promote_idx = step_names.index("promote_to_dc")
        assert install_idx < promote_idx, "install_ad_feature must come before promote_to_dc"

    def test_install_step_requires_reboot(self):
        """Install AD feature step requires reboot."""
        plan = DCSetupPlan()

        install_step = next(s for s in plan.steps if s.name == "install_ad_feature")
        assert install_step.requires_reboot is True

    def test_steps_have_adequate_timeouts(self):
        """Both AD steps have adequate timeouts for real-world execution."""
        plan = DCSetupPlan()

        install_step = next(s for s in plan.steps if s.name == "install_ad_feature")
        promote_step = next(s for s in plan.steps if s.name == "promote_to_dc")

        # Both steps need adequate time (typically 2-5 min each, plus buffer)
        assert install_step.timeout_seconds >= 300  # At least 5 min
        assert promote_step.timeout_seconds >= 300  # At least 5 min

    def test_all_steps_have_names(self):
        """All steps have descriptive names."""
        plan = DCSetupPlan()

        for step in plan.steps:
            assert step.name is not None
            assert len(step.name) > 0
            assert step.name != ""

    def test_all_steps_have_scripts(self):
        """All steps have non-empty scripts."""
        plan = DCSetupPlan()

        for step in plan.steps:
            assert step.script is not None
            assert len(step.script) > 0

    def test_all_steps_have_timeouts(self):
        """All steps have reasonable timeouts."""
        plan = DCSetupPlan()

        for step in plan.steps:
            assert step.timeout_seconds is not None
            assert step.timeout_seconds > 0
            assert step.timeout_seconds <= 3600  # Max 1 hour


class TestDCSetupPlanVerification:
    """Test DC setup plan verification step."""

    def test_has_verification_step(self):
        """Plan has a verification step."""
        plan = DCSetupPlan()

        assert plan.verify_step is not None
        assert isinstance(plan.verify_step, SetupStep)

    def test_verify_step_is_marked_as_verification(self):
        """Verification step has is_verification=True."""
        plan = DCSetupPlan()

        assert plan.verify_step.is_verification is True

    def test_verify_step_checks_ad_running(self):
        """Verification script actually checks if AD is running."""
        plan = DCSetupPlan()

        script = plan.verify_step.script.lower()
        # Should check AD DS in some way
        assert any(check in script for check in [
            "get-addomaincontroller",
            "get-addomain",
            "ad-domain-services",
            "dcdiag",
            "nltest",
            "ntds",
        ]), "Verification script should check AD DS status"


class TestDCSetupPlanContext:
    """Test get_context method."""

    def test_get_context_returns_all_vars(self):
        """get_context returns all required template variables."""
        plan = DCSetupPlan()
        instance = MockDCInstance()

        context = plan.get_context(instance)

        # Must have all these variables
        assert "domain_name" in context
        assert "netbios_name" in context
        assert "dsrm_password" in context
        assert "domain_admin_password" in context

        # Values should match instance
        assert context["domain_name"] == "shifter.local"
        assert context["netbios_name"] == "SHIFTER"
        assert context["dsrm_password"] == "DsrmPass123!"
        assert context["domain_admin_password"] == "AdminPass456!"

    def test_get_context_includes_hostname(self):
        """get_context includes hostname if available."""
        plan = DCSetupPlan()
        instance = MockDCInstance()

        context = plan.get_context(instance)

        # Hostname should be included for AD configuration
        assert "hostname" in context or "dc_hostname" in context

    def test_get_context_includes_ip(self):
        """get_context includes DC IP address."""
        plan = DCSetupPlan()
        instance = MockDCInstance()

        context = plan.get_context(instance)

        # IP should be included for DNS configuration
        assert "private_ip" in context or "dc_ip" in context

    def test_get_context_missing_attr_raises(self):
        """Instance missing required attribute raises clear error."""
        plan = DCSetupPlan()

        # Instance missing domain_name
        incomplete_instance = MagicMock()
        incomplete_instance.domain_name = None
        incomplete_instance.netbios_name = "SHIFTER"
        incomplete_instance.dsrm_password = "pass"
        incomplete_instance.domain_admin_password = "pass"

        with pytest.raises((AttributeError, ValueError, KeyError)) as exc_info:
            plan.get_context(incomplete_instance)

        # Should have clear error message


class TestDCSetupPlanScripts:
    """Test that scripts are valid PowerShell."""

    def test_install_script_uses_install_windowsfeature(self):
        """Install script uses Install-WindowsFeature cmdlet."""
        plan = DCSetupPlan()

        install_step = next(s for s in plan.steps if s.name == "install_ad_feature")
        script = install_step.script

        assert "Install-WindowsFeature" in script
        assert "AD-Domain-Services" in script

    def test_promote_script_uses_install_addsforest(self):
        """Promote script uses Install-ADDSForest cmdlet."""
        plan = DCSetupPlan()

        promote_step = next(s for s in plan.steps if s.name == "promote_to_dc")
        script = promote_step.script

        assert "Install-ADDSForest" in script

    def test_promote_script_uses_template_variables(self):
        """Promote script uses template variables for config."""
        plan = DCSetupPlan()

        promote_step = next(s for s in plan.steps if s.name == "promote_to_dc")
        script = promote_step.script

        # Should use Jinja2 template variables
        assert "{{ domain_name }}" in script or "{{domain_name}}" in script
        assert "{{ netbios_name }}" in script or "{{netbios_name}}" in script
        assert "{{ dsrm_password }}" in script or "{{dsrm_password}}" in script

    def test_scripts_handle_errors(self):
        """Scripts should have error handling."""
        plan = DCSetupPlan()

        for step in plan.steps:
            script = step.script
            # Should have some form of error handling
            assert any(handler in script for handler in [
                "$ErrorActionPreference",
                "-ErrorAction Stop",
                "try",
                "if ($LASTEXITCODE",
                "exit 1",
            ]), f"Step {step.name} should have error handling"


class TestDCSetupPlanInterface:
    """Test that DCSetupPlan implements SetupPlan interface."""

    def test_has_steps_attribute(self):
        """Plan has steps attribute (list of SetupStep)."""
        plan = DCSetupPlan()

        assert hasattr(plan, "steps")
        assert isinstance(plan.steps, list)
        for step in plan.steps:
            assert isinstance(step, SetupStep)

    def test_has_verify_step_attribute(self):
        """Plan has verify_step attribute (SetupStep)."""
        plan = DCSetupPlan()

        assert hasattr(plan, "verify_step")
        assert isinstance(plan.verify_step, SetupStep)

    def test_has_get_context_method(self):
        """Plan has get_context method."""
        plan = DCSetupPlan()

        assert hasattr(plan, "get_context")
        assert callable(plan.get_context)


class TestDCSetupPlanSecurity:
    """Test security considerations in DC setup plan."""

    def test_passwords_not_hardcoded(self):
        """Scripts don't contain hardcoded passwords."""
        plan = DCSetupPlan()

        for step in plan.steps:
            script = step.script.lower()
            # Should use template variables, not hardcoded values
            assert "password123" not in script
            assert "admin123" not in script
            assert "p@ssword" not in script

    def test_passwords_use_securestring(self):
        """Passwords are converted to SecureString in PowerShell."""
        plan = DCSetupPlan()

        promote_step = next(s for s in plan.steps if s.name == "promote_to_dc")
        script = promote_step.script

        # Password should be converted to SecureString
        assert "ConvertTo-SecureString" in script


class TestDCSetupPlanDNS:
    """Test DNS configuration in DC setup."""

    def test_installs_dns(self):
        """DC setup includes DNS installation."""
        plan = DCSetupPlan()

        promote_step = next(s for s in plan.steps if s.name == "promote_to_dc")
        script = promote_step.script

        # Should install DNS with AD
        assert "-InstallDns" in script or "DNS" in script


class TestDCSetupPlanRebootHandling:
    """Test reboot handling in DC setup plan."""

    def test_promote_requires_reboot(self):
        """AD promotion step requires reboot (DC restarts after promotion)."""
        plan = DCSetupPlan()

        promote_step = next(s for s in plan.steps if s.name == "promote_to_dc")

        # AD promotion causes automatic reboot
        assert promote_step.requires_reboot is True

    def test_at_least_two_reboots(self):
        """DC setup requires at least 2 reboots (feature install + promote)."""
        plan = DCSetupPlan()

        reboot_steps = [s for s in plan.steps if s.requires_reboot]

        # Should have at least 2 reboots
        assert len(reboot_steps) >= 2
