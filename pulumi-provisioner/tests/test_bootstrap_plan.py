"""Tests for BootstrapPlan.

Tests verify:
- Correct step ordering (hostname before SSH)
- Template variable handling
- Hostname step requires reboot
- SSH step does not require reboot
- No verification step (bootstrap success is implicit)
"""

from dataclasses import dataclass
from typing import Optional

import pytest

from components.plans.bootstrap import BootstrapPlan, SET_HOSTNAME_SCRIPT, CONFIGURE_SSH_SCRIPT


@dataclass
class MockInstance:
    """Mock instance for testing get_context."""
    hostname: Optional[str] = None
    public_key: str = ""


class TestBootstrapPlanSteps:
    """Test BootstrapPlan step definitions."""

    def test_has_two_steps(self):
        """BootstrapPlan should have exactly two steps."""
        plan = BootstrapPlan()
        assert len(plan.steps) == 2

    def test_steps_in_correct_order(self):
        """Hostname must be set before SSH is configured."""
        plan = BootstrapPlan()
        step_names = [s.name for s in plan.steps]
        assert step_names == ["set_hostname", "configure_ssh"]

    def test_hostname_step_requires_reboot(self):
        """Hostname change requires reboot to take effect."""
        plan = BootstrapPlan()
        hostname_step = next(s for s in plan.steps if s.name == "set_hostname")
        assert hostname_step.requires_reboot is True

    def test_ssh_step_does_not_require_reboot(self):
        """SSH configuration does not require reboot."""
        plan = BootstrapPlan()
        ssh_step = next(s for s in plan.steps if s.name == "configure_ssh")
        assert ssh_step.requires_reboot is False

    def test_all_steps_have_names(self):
        """All steps must have names for logging and debugging."""
        plan = BootstrapPlan()
        for step in plan.steps:
            assert step.name, "Step must have a name"

    def test_all_steps_have_scripts(self):
        """All steps must have script content."""
        plan = BootstrapPlan()
        for step in plan.steps:
            assert step.script, f"Step {step.name} must have a script"

    def test_all_steps_have_timeouts(self):
        """All steps must have reasonable timeouts."""
        plan = BootstrapPlan()
        for step in plan.steps:
            assert step.timeout_seconds > 0, f"Step {step.name} must have positive timeout"
            assert step.timeout_seconds <= 300, f"Step {step.name} timeout seems too long for bootstrap"


class TestBootstrapPlanVerification:
    """Test BootstrapPlan verification step (should be None)."""

    def test_no_verification_step(self):
        """Bootstrap has no verification step - success is implicit."""
        plan = BootstrapPlan()
        assert plan.verify_step is None


class TestBootstrapPlanContext:
    """Test BootstrapPlan.get_context()."""

    def test_get_context_returns_hostname(self):
        """get_context should return hostname."""
        plan = BootstrapPlan()
        instance = MockInstance(hostname="test-dc-1", public_key="ssh-ed25519 AAAA...")
        context = plan.get_context(instance)
        assert context["hostname"] == "test-dc-1"

    def test_get_context_returns_public_key(self):
        """get_context should return public_key."""
        plan = BootstrapPlan()
        instance = MockInstance(hostname="test-dc-1", public_key="ssh-ed25519 AAAA...")
        context = plan.get_context(instance)
        assert context["public_key"] == "ssh-ed25519 AAAA..."

    def test_get_context_missing_hostname_raises(self):
        """get_context should raise if hostname is missing."""
        plan = BootstrapPlan()
        instance = MockInstance(hostname=None)
        with pytest.raises(ValueError, match="hostname"):
            plan.get_context(instance)

    def test_get_context_empty_hostname_raises(self):
        """get_context should raise if hostname is empty."""
        plan = BootstrapPlan()
        instance = MockInstance(hostname="")
        with pytest.raises(ValueError, match="hostname"):
            plan.get_context(instance)

    def test_get_context_empty_public_key_allowed(self):
        """get_context should allow empty public_key (SSH still works with password)."""
        plan = BootstrapPlan()
        instance = MockInstance(hostname="test-dc-1", public_key="")
        context = plan.get_context(instance)
        assert context["public_key"] == ""


class TestBootstrapPlanScripts:
    """Test BootstrapPlan script content."""

    def test_hostname_script_uses_rename_computer(self):
        """Hostname script should use Rename-Computer cmdlet."""
        assert "Rename-Computer" in SET_HOSTNAME_SCRIPT

    def test_hostname_script_uses_template_variable(self):
        """Hostname script should use {{ hostname }} template variable."""
        assert "{{ hostname }}" in SET_HOSTNAME_SCRIPT

    def test_ssh_script_starts_service(self):
        """SSH script should start the sshd service."""
        assert "Start-Service sshd" in CONFIGURE_SSH_SCRIPT

    def test_ssh_script_sets_automatic_startup(self):
        """SSH script should set sshd to automatic startup."""
        assert "Set-Service" in CONFIGURE_SSH_SCRIPT
        assert "Automatic" in CONFIGURE_SSH_SCRIPT

    def test_ssh_script_uses_public_key_variable(self):
        """SSH script should use {{ public_key }} template variable."""
        assert "{{ public_key }}" in CONFIGURE_SSH_SCRIPT

    def test_ssh_script_sets_up_authorized_keys(self):
        """SSH script should configure administrators_authorized_keys."""
        assert "administrators_authorized_keys" in CONFIGURE_SSH_SCRIPT

    def test_ssh_script_sets_permissions(self):
        """SSH script should set proper permissions on authorized keys file."""
        assert "icacls" in CONFIGURE_SSH_SCRIPT

    def test_scripts_handle_errors(self):
        """Scripts should have error handling."""
        assert 'exit 1' in SET_HOSTNAME_SCRIPT
        assert 'exit 1' in CONFIGURE_SSH_SCRIPT
        assert '$ErrorActionPreference = "Stop"' in SET_HOSTNAME_SCRIPT
        assert '$ErrorActionPreference = "Stop"' in CONFIGURE_SSH_SCRIPT


class TestBootstrapPlanInterface:
    """Test BootstrapPlan conforms to SetupPlan interface."""

    def test_has_steps_attribute(self):
        """BootstrapPlan must have steps attribute."""
        plan = BootstrapPlan()
        assert hasattr(plan, "steps")
        assert isinstance(plan.steps, list)

    def test_has_verify_step_attribute(self):
        """BootstrapPlan must have verify_step attribute (even if None)."""
        plan = BootstrapPlan()
        assert hasattr(plan, "verify_step")

    def test_has_get_context_method(self):
        """BootstrapPlan must have get_context method."""
        plan = BootstrapPlan()
        assert hasattr(plan, "get_context")
        assert callable(plan.get_context)
