"""User data template tests for Shifter Engine."""

import base64
import sys
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

sys.path.insert(0, str(Path(__file__).parent.parent))


# The Linux GDC templates now render a provisioner-generated Ed25519 host key
# into cloud-init ``ssh_keys:`` (trusted-side-channel host verification). These
# tests exercise the raw templates, so the fixtures default representative
# host-key material; the Windows template ignores the extra kwargs.
_SAMPLE_HOST_PRIVATE_KEY = (
    "-----BEGIN OPENSSH PRIVATE KEY-----\n"
    "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZWQy\n"
    "NTUxOQAAACDTESTTESTTESTTESTTESTTESTTESTTESTTESTTESTTQAAAA==\n"
    "-----END OPENSSH PRIVATE KEY-----\n"
)
_SAMPLE_HOST_PUBLIC_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITESTHOSTKEY shifter-host"


class _HostKeyTemplate:
    """Wrap a Jinja template, defaulting the host-key vars the Linux GDC
    templates require so existing ``render()`` calls need not pass them."""

    def __init__(self, template):
        self._template = template

    def render(self, **kwargs):
        kwargs.setdefault("host_private_key", _SAMPLE_HOST_PRIVATE_KEY)
        kwargs.setdefault(
            "host_private_key_b64",
            base64.b64encode(_SAMPLE_HOST_PRIVATE_KEY.encode()).decode("ascii"),
        )
        kwargs.setdefault("host_public_key", _SAMPLE_HOST_PUBLIC_KEY)
        return self._template.render(**kwargs)


class TestKaliTemplate:
    """Tests for Kali attacker user data template."""

    @pytest.fixture
    def kali_template(self):
        """Load the Kali template."""
        templates_dir = Path(__file__).parent.parent / "templates"
        # select_autoescape() yields no escaping for these non-HTML (.sh/.ps1) templates
        env = Environment(loader=FileSystemLoader(str(templates_dir)), autoescape=select_autoescape())
        return _HostKeyTemplate(env.get_template("kali.sh.j2"))

    def test_kali_template_hostname(self, kali_template):
        """hostname variable should be replaced."""
        result = kali_template.render(
            hostname="shifter-kali-42",
            public_key="ssh-rsa AAAA... user@host",
        )
        assert "shifter-kali-42" in result
        assert "{{ hostname }}" not in result

    def test_kali_template_public_key(self, kali_template):
        """public_key variable should be replaced."""
        test_key = "ssh-rsa AAAAC3NzaC1lZDI1NTE5AAAAIExample test@localhost"
        result = kali_template.render(
            hostname="shifter-kali-42",
            public_key=test_key,
        )
        assert test_key in result
        assert "{{ public_key }}" not in result

    def test_kali_template_is_cloud_config_wrapping_bash(self, kali_template):
        """Output must be #cloud-config (GDC requirement) embedding a bash script."""
        import yaml

        result = kali_template.render(
            hostname="shifter-kali-42",
            public_key="ssh-rsa AAAA...",
        )
        # GDC VM Runtime rejects non-#cloud-config user-data (InvalidCloudInitUserdata).
        assert result.startswith("#cloud-config\n")
        doc = yaml.safe_load(result)
        assert doc["runcmd"] == ["/opt/shifter/gdc-user-data.sh"]
        script = next(e["content"] for e in doc["write_files"] if e["path"].endswith("gdc-user-data.sh"))
        assert script.startswith("#!/bin/bash")
        # Verify essential script components rather than arbitrary length
        assert "hostnamectl set-hostname" in script  # Must set hostname
        assert "authorized_keys" in script  # Must configure SSH
        assert "echo" in script  # Must have logging/output

    def test_kali_template_sets_hostname(self, kali_template):
        """Template should set hostname."""
        result = kali_template.render(
            hostname="shifter-kali-99",
            public_key="ssh-rsa AAAA...",
        )
        assert "hostnamectl set-hostname" in result

    def test_kali_template_configures_ssh(self, kali_template):
        """Template should configure SSH authorized_keys."""
        result = kali_template.render(
            hostname="shifter-kali-42",
            public_key="ssh-rsa AAAA...",
        )
        assert "authorized_keys" in result
        assert "/home/kali/.ssh" in result

    def test_kali_template_configures_desktop_services_without_baked_password(self, kali_template):
        # Issue #762: the per-instance password is set post-boot by the
        # engine provisioner via SSH; nothing about it lives in user_data.
        result = kali_template.render(
            hostname="shifter-kali-42",
            public_key="ssh-rsa AAAA...",
        )
        assert "CortexSavesTheDay!" not in result
        # No baked chpasswd / fetch-at-boot leftovers.
        assert "gcloud secrets versions access" not in result
        assert "aws secretsmanager get-secret-value" not in result
        import re

        chpasswd_pattern = re.compile(r'(?:echo\s+["\']?)([a-z]+):\1(?:["\']?\s*\|\s*chpasswd)')
        assert not chpasswd_pattern.search(result), result
        # Desktop services still wired.
        assert "apt-get install -y openssh-server xrdp" in result
        assert "PasswordAuthentication yes" in result
        assert "enable --now xrdp" in result


class TestVictimLinuxTemplate:
    """Tests for Linux victim user data template.

    user_data should configure SSH access (SSM can be flaky).
    Other setup (hostname, XDR) is handled by SSM plans.
    """

    @pytest.fixture
    def linux_template(self):
        """Load the Linux victim template."""
        templates_dir = Path(__file__).parent.parent / "templates"
        # select_autoescape() yields no escaping for these non-HTML (.sh) templates
        env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=select_autoescape(),
        )
        return _HostKeyTemplate(env.get_template("victim_linux.sh.j2"))

    def test_victim_linux_template_configures_ssh(self, linux_template):
        """Template should configure SSH access."""
        result = linux_template.render(
            public_key="ssh-rsa test-key",
            ssh_user="ubuntu",
        )
        # Should NOT set hostname (SSM does that)
        assert "hostnamectl" not in result
        # Should configure SSH access
        assert "authorized_keys" in result
        assert ".ssh" in result
        # Should NOT install XDR (SSM does that)
        assert "curl" not in result

    def test_victim_linux_template_is_cloud_config_wrapping_bash(self, linux_template):
        """Output must be #cloud-config (GDC requirement) embedding a bash script."""
        import yaml

        result = linux_template.render(
            public_key="ssh-rsa test-key",
            ssh_user="ubuntu",
        )
        # GDC VM Runtime rejects non-#cloud-config user-data (InvalidCloudInitUserdata).
        assert result.startswith("#cloud-config\n")
        doc = yaml.safe_load(result)
        assert doc["runcmd"] == ["/opt/shifter/gdc-user-data.sh"]
        script = next(e["content"] for e in doc["write_files"] if e["path"].endswith("gdc-user-data.sh"))
        assert script.startswith("#!/bin/bash")
        assert "set -euo pipefail" in script or "set -e" in script

    def test_victim_linux_template_explains_ssm(self, linux_template):
        """Template should explain that setup plans handle the remaining steps."""
        result = linux_template.render(
            public_key="ssh-rsa test-key",
            ssh_user="ubuntu",
        )
        assert "Shifter setup plans" in result

    def test_victim_linux_template_configures_services_without_baked_password(self, linux_template):
        # Issue #762: the per-instance password is set post-boot by the
        # engine provisioner via SSH; nothing about it lives in user_data.
        result = linux_template.render(
            public_key="ssh-rsa test-key",
            ssh_user="ubuntu",
        )
        # No baked chpasswd / fetch-at-boot leftovers.
        assert "gcloud secrets versions access" not in result
        assert "aws secretsmanager get-secret-value" not in result
        import re

        chpasswd_pattern = re.compile(r'(?:echo\s+["\']?)([a-z]+):\1(?:["\']?\s*\|\s*chpasswd)')
        assert not chpasswd_pattern.search(result), result
        # Desktop services still wired.
        assert "apt-get install -y openssh-server xrdp" in result
        assert "PasswordAuthentication yes" in result
        assert "enable --now xrdp" in result


class TestVictimWindowsTemplate:
    """Tests for Windows victim user data template.

    user_data should configure SSH/RDP access.
    Other setup (hostname, XDR) is handled by SSM plans.
    """

    @pytest.fixture
    def windows_template(self):
        """Load the Windows victim template."""
        templates_dir = Path(__file__).parent.parent / "templates"
        # select_autoescape() yields no escaping for these non-HTML (.sh/.ps1) templates
        env = Environment(loader=FileSystemLoader(str(templates_dir)), autoescape=select_autoescape())
        return env.get_template("victim_windows.ps1.j2")

    def test_victim_windows_template_configures_access(self, windows_template):
        """Template should configure SSH/RDP access."""
        result = windows_template.render(
            public_key="ssh-rsa test-key",
        )
        # Should NOT set hostname (SSM does that)
        assert "Rename-Computer" not in result
        # Should configure SSH
        assert "administrators_authorized_keys" in result
        assert "sshd" in result
        # Should NOT install XDR (SSM does that)
        assert "Invoke-WebRequest" not in result

    def test_victim_windows_template_valid_powershell(self, windows_template):
        """Output should be a valid PowerShell script."""
        result = windows_template.render(
            public_key="ssh-rsa test-key",
        )
        assert "<powershell>" in result
        assert "</powershell>" in result

    def test_victim_windows_template_explains_ssm(self, windows_template):
        """Template should explain that setup plans handle the remaining steps."""
        result = windows_template.render(
            public_key="ssh-rsa test-key",
        )
        assert "Shifter setup plans" in result

    def test_victim_windows_template_enables_access_services(self, windows_template):
        result = windows_template.render(
            public_key="ssh-rsa test-key",
        )
        assert "OpenSSH.Server" in result
        assert 'Enable-NetFirewallRule -DisplayGroup "Remote Desktop"' in result
        assert "fDenyTSConnections" in result


class TestTemplateContentSafety:
    """Tests for template content safety."""

    @pytest.fixture
    def all_templates(self):
        """Load all templates."""
        templates_dir = Path(__file__).parent.parent / "templates"
        # select_autoescape() yields no escaping for these non-HTML (.sh/.ps1) templates
        env = Environment(loader=FileSystemLoader(str(templates_dir)), autoescape=select_autoescape())
        return {
            "kali": _HostKeyTemplate(env.get_template("kali.sh.j2")),
            "linux": _HostKeyTemplate(env.get_template("victim_linux.sh.j2")),
            "windows": _HostKeyTemplate(env.get_template("victim_windows.ps1.j2")),
        }

    def test_templates_use_strict_bash_mode(self, all_templates):
        """Linux templates should use set -euo pipefail."""
        # Kali needs hostname/public_key
        kali_result = all_templates["kali"].render(
            hostname="test",
            public_key="test",
        )
        linux_result = all_templates["linux"].render(
            public_key="ssh-rsa test-key",
            ssh_user="ubuntu",
        )
        assert "set -euo pipefail" in kali_result or "set -e" in kali_result
        assert "set -euo pipefail" in linux_result or "set -e" in linux_result

    def test_windows_uses_error_action_stop(self, all_templates):
        """Windows template should use ErrorActionPreference Stop."""
        result = all_templates["windows"].render(
            public_key="ssh-rsa test-key",
        )
        assert "ErrorActionPreference" in result and "Stop" in result

    def test_templates_log_output(self, all_templates):
        """Templates should log their output for debugging."""
        # Kali needs hostname/public_key
        kali_result = all_templates["kali"].render(
            hostname="test",
            public_key="test",
        )
        assert "log" in kali_result.lower() or "echo" in kali_result.lower()

        # Victim templates should log output too
        linux_result = all_templates["linux"].render(
            public_key="ssh-rsa test-key",
            ssh_user="ubuntu",
        )
        windows_result = all_templates["windows"].render(
            public_key="ssh-rsa test-key",
        )
        assert "log" in linux_result.lower() or "echo" in linux_result.lower()
        assert "log" in windows_result.lower() or "Write-Host" in windows_result


class TestGdcCloudInitMerge:
    """Guard the GDC VM Runtime cloud-init merge contract.

    GDC's VM controller text-injects its own ``write_files`` entry
    (``/var/lib/cloud/scripts/per-boot/google_boot_init.sh``) immediately
    after the ``write_files:`` key, as a flush-left (indent-0) block-sequence
    item. If our own ``write_files`` items are indented (``  - path:``), the
    merged document mixes indent-0 and indent-2 sequence items, which is
    invalid YAML ("expected <block end>, but found '-'"). cloud-init then
    discards the *entire* config, so ``ssh_keys``/``write_files``/``runcmd``
    never apply and the guest serves a boot-generated host key (range setup
    then fails host-key verification). Our list items must be flush-left so
    the merged sequence stays uniform.
    """

    # Captured live from a GDC range VM's regenerated kubevm cloud-init secret.
    _GDC_INJECTED_WRITE_FILE = (
        "- path: /var/lib/cloud/scripts/per-boot/google_boot_init.sh\n"
        "  encoding: b64\n"
        "  permissions: '0744'\n"
        "  content: IyEvYmluL2Jhc2gKZWNobyBoaQo=\n"
    )

    @pytest.fixture
    def linux_templates(self):
        templates_dir = Path(__file__).parent.parent / "templates"
        env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=select_autoescape(["html", "xml"]),
        )
        return {
            "kali": _HostKeyTemplate(env.get_template("kali.sh.j2")),
            "linux": _HostKeyTemplate(env.get_template("victim_linux.sh.j2")),
        }

    @pytest.mark.parametrize("which", ["kali", "linux"])
    def test_write_files_items_are_flush_left(self, linux_templates, which):
        """write_files / runcmd list items must sit at indent 0 (no leading spaces)."""
        result = linux_templates[which].render(hostname="h", public_key="ssh-rsa AAAA x@y", ssh_user="ubuntu")
        # Flush-left list items present; no 2-space-indented items anywhere
        # (a 2-space-indented `- path:` next to GDC's indent-0 item breaks YAML).
        assert "\n- path:" in result
        assert "\n  - path:" not in result
        assert "\nruncmd:\n- " in result
        assert "\nruncmd:\n  - " not in result

    @pytest.mark.parametrize("which", ["kali", "linux"])
    def test_authorized_keys_installed_in_early_write_files_stage(self, linux_templates, which):
        """The runner key must be installed via write_files (early cloud-init stage),
        not only in the final-stage runcmd, so auth works even when a guest's final
        stage stalls (e.g. the heavy Kali desktop image)."""
        import yaml

        result = linux_templates[which].render(hostname="h", public_key="ssh-rsa AAAAKEY x@y", ssh_user="ubuntu")
        doc = yaml.safe_load(result)
        ak = [e for e in doc["write_files"] if e["path"].endswith("/.ssh/authorized_keys")]
        assert len(ak) == 1, "expected exactly one authorized_keys write_files entry"
        entry = ak[0]
        assert entry["permissions"] == "0600"
        assert "ssh-rsa AAAAKEY x@y" in entry["content"]
        # Owner must be the connecting user, not root.
        assert entry["owner"].split(":")[0] in entry["path"]

    @pytest.mark.parametrize("which", ["kali", "linux"])
    def test_survives_gdc_write_files_injection(self, linux_templates, which):
        """A simulated GDC per-boot write_files injection must keep the doc valid YAML."""
        import yaml

        result = linux_templates[which].render(hostname="h", public_key="ssh-rsa AAAA x@y", ssh_user="ubuntu")
        merged = result.replace("write_files:\n", "write_files:\n" + self._GDC_INJECTED_WRITE_FILE, 1)
        doc = yaml.safe_load(merged)
        paths = [e.get("path") for e in doc["write_files"]]
        assert "/var/lib/cloud/scripts/per-boot/google_boot_init.sh" in paths
        assert "/opt/shifter/gdc-user-data.sh" in paths
        assert doc["runcmd"] == ["/opt/shifter/gdc-user-data.sh"]
