"""Tests for BootstrapPlan."""

from dataclasses import dataclass

import pytest

from plans.bootstrap import BootstrapPlan


@dataclass
class MockInstance:
    """Mock instance for testing get_context."""

    hostname: str | None = None
    public_key: str = ""


class TestBootstrapPlan:
    """Tests for BootstrapPlan behavior."""

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

    def test_get_context_returns_expected_values(self):
        """get_context returns hostname and public_key."""
        plan = BootstrapPlan()
        instance = MockInstance(hostname="test-dc-1", public_key="ssh-ed25519 AAAA")
        context = plan.get_context(instance)
        assert context["hostname"] == "test-dc-1"
        assert context["public_key"] == "ssh-ed25519 AAAA"

    def test_get_context_missing_hostname_raises(self):
        """get_context raises if hostname is missing."""
        plan = BootstrapPlan()
        instance = MockInstance(hostname=None)
        with pytest.raises(ValueError, match="hostname"):
            plan.get_context(instance)

    def test_get_context_empty_hostname_raises(self):
        """get_context raises if hostname is empty."""
        plan = BootstrapPlan()
        instance = MockInstance(hostname="")
        with pytest.raises(ValueError, match="hostname"):
            plan.get_context(instance)
