"""Tests for DCSetupPlan.

DCSetupPlan defines the specific steps to promote a Windows Server
(with AD DS feature prebaked in AMI) to a Domain Controller.
"""

from unittest.mock import MagicMock
from dataclasses import dataclass

import pytest

from components.plans.dc_setup import DCSetupPlan
from components.setup_plan import SetupStep


@dataclass
class MockDCInstance:
    """Mock DC instance for testing."""
    domain_name: str = "shifter.local"
    netbios_name: str = "SHIFTER"
    dsrm_password: str = "DsrmPass123!"
    domain_admin_password: str = "AdminPass456!"


class TestDCSetupPlanSteps:
    """Test DC setup plan step definitions."""

    def test_has_promote_step(self):
        """Plan has promote_to_dc step."""
        plan = DCSetupPlan()

        step_names = [step.name for step in plan.steps]
        assert "promote_to_dc" in step_names

    def test_promote_step_requires_reboot(self):
        """Promote step requires reboot."""
        plan = DCSetupPlan()

        promote_step = next(s for s in plan.steps if s.name == "promote_to_dc")
        assert promote_step.requires_reboot is True

    def test_all_steps_have_timeouts(self):
        """All steps must have positive timeouts."""
        plan = DCSetupPlan()
        for step in plan.steps:
            assert step.timeout_seconds is not None, f"Step {step.name} missing timeout"
            assert step.timeout_seconds > 0, f"Step {step.name} must have positive timeout"

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

    def test_timeouts_are_reasonable(self):
        """All steps have reasonable timeouts (max 1 hour)."""
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

    def test_get_context_missing_attr_raises(self):
        """Instance missing required attribute raises clear error."""
        plan = DCSetupPlan()

        # Instance missing domain_name
        incomplete_instance = MagicMock()
        incomplete_instance.domain_name = None
        incomplete_instance.netbios_name = "SHIFTER"
        incomplete_instance.dsrm_password = "pass"
        incomplete_instance.domain_admin_password = "pass"

        with pytest.raises((AttributeError, ValueError, KeyError)):
            plan.get_context(incomplete_instance)


class TestDCSetupPlanScripts:
    """Test that scripts are valid PowerShell."""

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


class TestDCSetupPlanDocstring:
    """Test DCSetupPlan docstring is accurate."""

    def test_docstring_does_not_claim_bootstrap_runs_first(self):
        """DCSetupPlan docstring should NOT claim BootstrapPlan runs first.

        DC instances use prebaked AMI where hostname/SSH are configured via
        user_data, NOT BootstrapPlan. The docstring must not mislead.
        """
        docstring = DCSetupPlan.__doc__ or ""
        # Should NOT claim BootstrapPlan runs first (it doesn't for DC)
        assert "AFTER BootstrapPlan" not in docstring
        assert "after BootstrapPlan" not in docstring.lower()


class TestDCSetupPlanRebootHandling:
    """Test reboot handling in DC setup plan."""

    def test_promote_requires_reboot(self):
        """AD promotion step requires reboot (DC restarts after promotion)."""
        plan = DCSetupPlan()

        promote_step = next(s for s in plan.steps if s.name == "promote_to_dc")

        # AD promotion causes automatic reboot
        assert promote_step.requires_reboot is True

    def test_single_reboot_with_prebaked_ami(self):
        """With prebaked AMI, DC setup only needs 1 reboot (promote only)."""
        plan = DCSetupPlan()

        reboot_steps = [s for s in plan.steps if s.requires_reboot]

        # AD DS feature is prebaked, so only promote step needs reboot
        assert len(reboot_steps) == 1
        assert reboot_steps[0].name == "promote_to_dc"
