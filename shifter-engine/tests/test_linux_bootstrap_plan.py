"""Tests for LinuxBootstrapPlan - only meaningful tests."""

from dataclasses import dataclass
from typing import Optional

import pytest

from components.plans.linux_bootstrap import LinuxBootstrapPlan


@dataclass
class MockLinuxInstance:
    hostname: Optional[str] = None
    public_key: str = ""
    ssh_user: str = "ubuntu"


class TestLinuxBootstrapPlanContext:
    """Test context generation and validation."""

    def test_get_context_returns_required_fields(self):
        """get_context returns hostname, public_key, and ssh_user."""
        plan = LinuxBootstrapPlan()
        instance = MockLinuxInstance(hostname="shifter-victim-1", public_key="ssh-key", ssh_user="ec2-user")
        context = plan.get_context(instance)
        assert context["hostname"] == "shifter-victim-1"
        assert context["public_key"] == "ssh-key"
        assert context["ssh_user"] == "ec2-user"

    def test_get_context_missing_hostname_raises(self):
        """get_context raises ValueError if hostname is missing."""
        plan = LinuxBootstrapPlan()
        instance = MockLinuxInstance(hostname=None)
        with pytest.raises(ValueError, match="hostname"):
            plan.get_context(instance)

    def test_get_context_empty_hostname_raises(self):
        """get_context raises ValueError if hostname is empty."""
        plan = LinuxBootstrapPlan()
        instance = MockLinuxInstance(hostname="")
        with pytest.raises(ValueError, match="hostname"):
            plan.get_context(instance)

    def test_get_context_defaults_ssh_user_to_ubuntu(self):
        """ssh_user defaults to 'ubuntu' if not specified."""
        plan = LinuxBootstrapPlan()

        @dataclass
        class NoSshUser:
            hostname: str = "test"
            public_key: str = ""

        instance = NoSshUser()
        context = plan.get_context(instance)
        assert context["ssh_user"] == "ubuntu"

    def test_get_context_works_for_kali_user(self):
        """LinuxBootstrapPlan works for Kali instances with ssh_user='kali'.

        This replaced the now-deleted KaliSetupPlan.
        """
        plan = LinuxBootstrapPlan()
        instance = MockLinuxInstance(
            hostname="shifter-kali-1",
            public_key="ssh-ed25519 AAAA...",
            ssh_user="kali",
        )
        context = plan.get_context(instance)
        assert context["ssh_user"] == "kali"
        assert context["hostname"] == "shifter-kali-1"
        assert context["public_key"] == "ssh-ed25519 AAAA..."
