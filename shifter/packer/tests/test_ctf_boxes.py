"""Workshop CTF box regression tests.

These tests stay scoped to the workshop-specific AMI scripts so changes here do
not impose new requirements on the shared platform images.
"""

from pathlib import Path

PACKER_DIR = Path(__file__).parent.parent
CTF_SCRIPTS_DIR = PACKER_DIR / "scripts" / "ctf"


def _read(*parts: str) -> str:
    return (CTF_SCRIPTS_DIR.joinpath(*parts)).read_text()


def test_linux_boxes_enforce_effective_ssh_password_auth() -> None:
    """Workshop Linux boxes must override cloud-image SSH password auth."""
    for box in ("webshell", "mailroom", "devbox"):
        content = _read(box, "setup.sh")
        assert "/etc/ssh/sshd_config.d/99-shifter-password-auth.conf" in content
        assert "PasswordAuthentication yes" in content
        assert "systemctl restart ssh" in content


def test_linux_boxes_wait_for_background_apt_work() -> None:
    """Workshop Ubuntu boxes must tolerate unattended-upgrades on first boot."""
    for box in ("webshell", "mailroom", "devbox"):
        content = _read(box, "setup.sh")
        assert "wait_for_apt()" in content
        assert "apt_update()" in content
        assert "apt_install()" in content
        assert "/var/lib/dpkg/lock-frontend" in content
        assert "pgrep -x unattended-upgr" in content
        assert "stop_background_apt()" in content
        assert "systemctl stop apt-daily.service apt-daily-upgrade.service unattended-upgrades.service" in content
        assert "pkill -f '/usr/share/unattended-upgrades/unattended-upgrade-shutdown --wait-for-signal'" in content
        assert "wait_for_apt" in content


def test_linux_box_validation_checks_effective_sshd_config() -> None:
    """Validation scripts should test the rendered sshd config, not one file."""
    for box in ("webshell", "mailroom", "devbox"):
        content = _read(box, "test.sh")
        assert "sshd -T" in content
        assert "passwordauthentication yes" in content


def test_webshell_template_has_extended_ssh_timeout() -> None:
    """WebShell should tolerate slow SSH readiness before provisioning starts."""
    content = (PACKER_DIR / "ctf-webshell.pkr.hcl").read_text()
    assert 'ssh_timeout  = "10m"' in content


def test_devbox_template_has_extended_ssh_timeout() -> None:
    """DevBox should tolerate slow SSH readiness before provisioning starts."""
    content = (PACKER_DIR / "ctf-devbox.pkr.hcl").read_text()
    assert 'ssh_timeout  = "10m"' in content


def test_helpdesk_user_is_not_local_admin() -> None:
    """HelpDesk should require the scheduled-task privesc path."""
    content = _read("helpdesk", "setup.ps1")
    assert 'Add-LocalGroupMember -Group "Administrators" -Member "helpdesk"' not in content
    assert 'Add-LocalGroupMember -Group "Remote Desktop Users" -Member "helpdesk"' in content
    assert 'Add-LocalGroupMember -Group "Remote Management Users" -Member "helpdesk"' in content
    assert 'DisplayName "RDP Inbound"' in content


def test_devbox_does_not_pin_vault_to_a_fixed_ip() -> None:
    """The workshop scenario uses one target subnet, so Vault IP is not fixed."""
    content = _read("devbox", "setup.sh")
    assert "VAULT_HOST=10.0.2.10" not in content
    assert "10.0.2.0/24" not in content
    assert "VAULT_ADMIN=vaultadmin" in content
    assert "VAULT_PASS=DevOps2024!" in content


def test_vault_uses_delayed_password_override_task() -> None:
    """Vault must win after the shared Windows victim user_data runs."""
    content = _read("vault", "setup.ps1")
    assert "Start-Sleep -Seconds 180" in content
    assert 'Register-ScheduledTask -TaskName "SetAdminPassword"' in content
    assert "V4ultAdm!n2024" in content
    assert "10.0.2.0/24" not in content
