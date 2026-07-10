"""Tests for LinuxBootstrapPlan - only meaningful tests."""

from dataclasses import dataclass

import pytest

from plans.linux_bootstrap import SET_HOSTNAME_SCRIPT, LinuxBootstrapPlan


@dataclass
class MockLinuxInstance:
    hostname: str | None = None
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
            public_key="ssh-rsa AAAA...",
            ssh_user="kali",
        )
        context = plan.get_context(instance)
        assert context["ssh_user"] == "kali"
        assert context["hostname"] == "shifter-kali-1"
        assert context["public_key"] == "ssh-rsa AAAA..."


class TestSetHostnamePrivilegeEscalation:
    """The set_hostname step must work on both remote-execution backends.

    AWS SSM runs the script as root; the GDC in-range SSH path connects as an
    unprivileged user (ubuntu/kali). ``hostnamectl set-hostname`` and writing
    ``/etc/hosts`` both require root, so the script must escalate with
    ``sudo -n`` when not already root (it failed on GDC with
    "Could not set static hostname: Interactive authentication required").
    """

    def test_escalates_privilege_when_not_root(self):
        # Resolves an empty SUDO as root and `sudo -n` otherwise.
        assert 'if [ "$(id -u)" -eq 0 ]; then' in SET_HOSTNAME_SCRIPT
        assert 'SUDO="sudo -n"' in SET_HOSTNAME_SCRIPT

    def test_privileged_commands_run_through_sudo_wrapper(self):
        # The root-only operations must go through $SUDO, not run bare.
        assert "$SUDO hostnamectl set-hostname" in SET_HOSTNAME_SCRIPT
        assert "| $SUDO tee -a /etc/hosts" in SET_HOSTNAME_SCRIPT
        # No bare invocations that would fail as a non-root SSH user.
        assert "\nhostnamectl set-hostname" not in SET_HOSTNAME_SCRIPT
        assert ">> /etc/hosts" not in SET_HOSTNAME_SCRIPT
