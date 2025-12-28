"""Tests for DomainJoinPlan.

DomainJoinPlan defines the steps to join a Windows machine to an AD domain.
This plan is executed by the DC after promotion completes.
"""

from unittest.mock import MagicMock

import pytest

from components.plans.domain_join import DomainJoinPlan
from components.setup_plan import SetupStep


class TestDomainJoinPlanSteps:
    """Test domain join plan step definitions."""

    def test_has_set_dns_step(self):
        """Plan has set_dns step."""
        plan = DomainJoinPlan()

        step_names = [step.name for step in plan.steps]
        assert "set_dns" in step_names

    def test_has_join_domain_step(self):
        """Plan has join_domain step."""
        plan = DomainJoinPlan()

        step_names = [step.name for step in plan.steps]
        assert "join_domain" in step_names

    def test_join_domain_requires_reboot(self):
        """Join domain step requires reboot."""
        plan = DomainJoinPlan()

        join_step = next(s for s in plan.steps if s.name == "join_domain")
        assert join_step.requires_reboot is True

    def test_set_dns_does_not_require_reboot(self):
        """Set DNS step does not require reboot."""
        plan = DomainJoinPlan()

        dns_step = next(s for s in plan.steps if s.name == "set_dns")
        assert dns_step.requires_reboot is False

    def test_all_steps_have_timeouts(self):
        """All steps must have positive timeouts."""
        plan = DomainJoinPlan()
        for step in plan.steps:
            assert step.timeout_seconds is not None, f"Step {step.name} missing timeout"
            assert step.timeout_seconds > 0, f"Step {step.name} must have positive timeout"

    def test_all_steps_have_names(self):
        """All steps have descriptive names."""
        plan = DomainJoinPlan()

        for step in plan.steps:
            assert step.name is not None
            assert len(step.name) > 0

    def test_all_steps_have_scripts(self):
        """All steps have non-empty scripts."""
        plan = DomainJoinPlan()

        for step in plan.steps:
            assert step.script is not None
            assert len(step.script) > 0

    def test_steps_in_correct_order(self):
        """DNS must be set before domain join."""
        plan = DomainJoinPlan()

        step_names = [step.name for step in plan.steps]
        dns_index = step_names.index("set_dns")
        join_index = step_names.index("join_domain")
        assert dns_index < join_index, "DNS must be set before domain join"


class TestDomainJoinPlanVerification:
    """Test domain join plan verification step."""

    def test_has_verification_step(self):
        """Plan has a verification step."""
        plan = DomainJoinPlan()

        assert plan.verify_step is not None
        assert isinstance(plan.verify_step, SetupStep)

    def test_verify_step_is_marked_as_verification(self):
        """Verification step has is_verification=True."""
        plan = DomainJoinPlan()

        assert plan.verify_step.is_verification is True

    def test_verify_step_checks_domain_membership(self):
        """Verification script checks domain membership."""
        plan = DomainJoinPlan()

        script = plan.verify_step.script.lower()
        # Should check domain membership in some way
        assert any(check in script for check in [
            "win32_computersystem",
            "domain",
            "get-wmiobject",
        ]), "Verification script should check domain membership"


class TestDomainJoinPlanContext:
    """Test get_context method."""

    def test_get_context_returns_all_vars(self):
        """get_context returns all required template variables."""
        plan = DomainJoinPlan()
        dc_config = {
            "dc_ip": "10.0.0.10",
            "domain_name": "test.local",
            "domain_admin_password": "TestPass123!",
        }

        context = plan.get_context(dc_config)

        # Must have all these variables
        assert "dc_ip" in context
        assert "domain_name" in context
        assert "domain_admin_user" in context
        assert "domain_admin_password" in context

        # Values should match config
        assert context["dc_ip"] == "10.0.0.10"
        assert context["domain_name"] == "test.local"
        assert context["domain_admin_password"] == "TestPass123!"
        # Default admin user
        assert context["domain_admin_user"] == "Administrator"

    def test_get_context_custom_admin_user(self):
        """get_context uses custom admin user if provided."""
        plan = DomainJoinPlan()
        dc_config = {
            "dc_ip": "10.0.0.10",
            "domain_name": "test.local",
            "domain_admin_password": "TestPass123!",
            "domain_admin_user": "DomainAdmin",
        }

        context = plan.get_context(dc_config)
        assert context["domain_admin_user"] == "DomainAdmin"

    def test_get_context_missing_dc_ip_raises(self):
        """Missing dc_ip raises clear error."""
        plan = DomainJoinPlan()
        dc_config = {
            "domain_name": "test.local",
            "domain_admin_password": "TestPass123!",
        }

        with pytest.raises(ValueError) as exc_info:
            plan.get_context(dc_config)
        assert "dc_ip" in str(exc_info.value)

    def test_get_context_missing_domain_name_raises(self):
        """Missing domain_name raises clear error."""
        plan = DomainJoinPlan()
        dc_config = {
            "dc_ip": "10.0.0.10",
            "domain_admin_password": "TestPass123!",
        }

        with pytest.raises(ValueError) as exc_info:
            plan.get_context(dc_config)
        assert "domain_name" in str(exc_info.value)

    def test_get_context_missing_password_raises(self):
        """Missing domain_admin_password raises clear error."""
        plan = DomainJoinPlan()
        dc_config = {
            "dc_ip": "10.0.0.10",
            "domain_name": "test.local",
        }

        with pytest.raises(ValueError) as exc_info:
            plan.get_context(dc_config)
        assert "domain_admin_password" in str(exc_info.value)

    def test_get_context_none_value_raises(self):
        """None value for required key raises error."""
        plan = DomainJoinPlan()
        dc_config = {
            "dc_ip": None,
            "domain_name": "test.local",
            "domain_admin_password": "TestPass123!",
        }

        with pytest.raises(ValueError):
            plan.get_context(dc_config)


class TestDomainJoinPlanScripts:
    """Test that scripts are valid PowerShell."""

    def test_set_dns_script_uses_template_variables(self):
        """Set DNS script uses dc_ip template variable."""
        plan = DomainJoinPlan()

        dns_step = next(s for s in plan.steps if s.name == "set_dns")
        script = dns_step.script

        assert "{{ dc_ip }}" in script or "{{dc_ip}}" in script

    def test_join_domain_script_uses_template_variables(self):
        """Join domain script uses template variables."""
        plan = DomainJoinPlan()

        join_step = next(s for s in plan.steps if s.name == "join_domain")
        script = join_step.script

        assert "{{ domain_name }}" in script or "{{domain_name}}" in script
        assert "{{ domain_admin_user }}" in script or "{{domain_admin_user}}" in script
        assert "{{ domain_admin_password }}" in script or "{{domain_admin_password}}" in script

    def test_scripts_handle_errors(self):
        """Scripts should have error handling."""
        plan = DomainJoinPlan()

        for step in plan.steps:
            script = step.script
            # Should have some form of error handling
            assert any(handler in script for handler in [
                "$ErrorActionPreference",
                "-ErrorAction Stop",
                "try",
                "exit 1",
            ]), f"Step {step.name} should have error handling"

    def test_join_script_uses_add_computer(self):
        """Join domain script uses Add-Computer cmdlet."""
        plan = DomainJoinPlan()

        join_step = next(s for s in plan.steps if s.name == "join_domain")
        assert "Add-Computer" in join_step.script

    def test_dns_script_uses_set_dnsclientserveraddress(self):
        """Set DNS script uses Set-DnsClientServerAddress cmdlet."""
        plan = DomainJoinPlan()

        dns_step = next(s for s in plan.steps if s.name == "set_dns")
        assert "Set-DnsClientServerAddress" in dns_step.script


class TestDomainJoinPlanInterface:
    """Test that DomainJoinPlan implements SetupPlan interface."""

    def test_has_steps_attribute(self):
        """Plan has steps attribute (list of SetupStep)."""
        plan = DomainJoinPlan()

        assert hasattr(plan, "steps")
        assert isinstance(plan.steps, list)
        for step in plan.steps:
            assert isinstance(step, SetupStep)

    def test_has_verify_step_attribute(self):
        """Plan has verify_step attribute (SetupStep)."""
        plan = DomainJoinPlan()

        assert hasattr(plan, "verify_step")
        assert isinstance(plan.verify_step, SetupStep)

    def test_has_get_context_method(self):
        """Plan has get_context method."""
        plan = DomainJoinPlan()

        assert hasattr(plan, "get_context")
        assert callable(plan.get_context)


class TestDomainJoinPlanSecurity:
    """Test security considerations in domain join plan."""

    def test_passwords_not_hardcoded(self):
        """Scripts don't contain hardcoded passwords."""
        plan = DomainJoinPlan()

        for step in plan.steps:
            script = step.script.lower()
            # Should use template variables, not hardcoded values
            assert "password123" not in script
            assert "admin123" not in script
            assert "p@ssword" not in script

    def test_password_uses_securestring(self):
        """Password is converted to SecureString in PowerShell."""
        plan = DomainJoinPlan()

        join_step = next(s for s in plan.steps if s.name == "join_domain")
        script = join_step.script

        # Password should be converted to SecureString
        assert "ConvertTo-SecureString" in script


class TestDomainJoinPlanRebootHandling:
    """Test reboot handling in domain join plan."""

    def test_only_join_requires_reboot(self):
        """Only the join_domain step requires reboot."""
        plan = DomainJoinPlan()

        reboot_steps = [s for s in plan.steps if s.requires_reboot]

        assert len(reboot_steps) == 1
        assert reboot_steps[0].name == "join_domain"

    def test_step_count(self):
        """Plan has exactly 2 steps (dns + join)."""
        plan = DomainJoinPlan()

        assert len(plan.steps) == 2
