"""User data template tests for Shifter Engine.

Tests template rendering for EC2 instance user data scripts.
"""

import base64
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestKaliTemplate:
    """Tests for Kali attacker user data template."""

    @pytest.fixture
    def kali_template(self):
        """Load the Kali template."""
        templates_dir = Path(__file__).parent.parent / "templates"
        # NOSONAR: autoescape=False - these are shell/PowerShell templates, not HTML
        env = Environment(loader=FileSystemLoader(str(templates_dir)), autoescape=False)
        return env.get_template("kali.sh.j2")

    def test_kali_template_hostname(self, kali_template):
        """hostname variable should be replaced."""
        result = kali_template.render(
            hostname="shifter-kali-42",
            public_key="ssh-ed25519 AAAA... user@host",
        )
        assert "shifter-kali-42" in result
        assert "{{ hostname }}" not in result

    def test_kali_template_public_key(self, kali_template):
        """public_key variable should be replaced."""
        test_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample test@localhost"
        result = kali_template.render(
            hostname="shifter-kali-42",
            public_key=test_key,
        )
        assert test_key in result
        assert "{{ public_key }}" not in result

    def test_kali_template_valid_bash(self, kali_template):
        """Output should be a valid bash script with required sections."""
        result = kali_template.render(
            hostname="shifter-kali-42",
            public_key="ssh-ed25519 AAAA...",
        )
        assert result.strip().startswith("#!/bin/bash")
        # Verify essential script components rather than arbitrary length
        assert "hostnamectl set-hostname" in result  # Must set hostname
        assert "authorized_keys" in result  # Must configure SSH
        assert "echo" in result  # Must have logging/output

    def test_kali_template_sets_hostname(self, kali_template):
        """Template should set hostname."""
        result = kali_template.render(
            hostname="shifter-kali-99",
            public_key="ssh-ed25519 AAAA...",
        )
        assert "hostnamectl set-hostname" in result

    def test_kali_template_configures_ssh(self, kali_template):
        """Template should configure SSH authorized_keys."""
        result = kali_template.render(
            hostname="shifter-kali-42",
            public_key="ssh-ed25519 AAAA...",
        )
        assert "authorized_keys" in result
        assert "/home/kali/.ssh" in result


class TestVictimLinuxTemplate:
    """Tests for Linux victim user data template.

    user_data should be MINIMAL - just enough to log boot.
    All real setup (hostname, SSH, XDR) is handled by SSM plans.
    """

    @pytest.fixture
    def linux_template(self):
        """Load the Linux victim template."""
        templates_dir = Path(__file__).parent.parent / "templates"
        # NOSONAR: autoescape=False - shell templates, not HTML
        env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=False,
        )
        return env.get_template("victim_linux.sh.j2")

    def test_victim_linux_template_is_minimal(self, linux_template):
        """Template should be minimal - no hostname or SSH setup."""
        result = linux_template.render()
        # Should NOT set hostname (SSM does that)
        assert "hostnamectl" not in result
        # Should NOT configure SSH (SSM does that)
        assert "authorized_keys" not in result
        assert ".ssh" not in result
        # Should NOT install XDR (SSM does that)
        assert "curl" not in result

    def test_victim_linux_template_valid_bash(self, linux_template):
        """Output should be a valid bash script."""
        result = linux_template.render()
        assert result.strip().startswith("#!/bin/bash")
        assert "set -euo pipefail" in result or "set -e" in result

    def test_victim_linux_template_explains_ssm(self, linux_template):
        """Template should explain that SSM handles setup."""
        result = linux_template.render()
        assert "SSM" in result


class TestVictimWindowsTemplate:
    """Tests for Windows victim user data template.

    user_data should be MINIMAL - just enough to log boot.
    All real setup (hostname, SSH, XDR) is handled by SSM plans.
    """

    @pytest.fixture
    def windows_template(self):
        """Load the Windows victim template."""
        templates_dir = Path(__file__).parent.parent / "templates"
        # NOSONAR: autoescape=False - these are shell/PowerShell templates, not HTML
        env = Environment(loader=FileSystemLoader(str(templates_dir)), autoescape=False)
        return env.get_template("victim_windows.ps1.j2")

    def test_victim_windows_template_is_minimal(self, windows_template):
        """Template should be minimal - no hostname or SSH setup."""
        result = windows_template.render()
        # Should NOT set hostname (SSM does that)
        assert "Rename-Computer" not in result
        # Should NOT configure SSH (SSM does that)
        assert "authorized_keys" not in result
        assert "sshd" not in result
        # Should NOT install XDR (SSM does that)
        assert "Invoke-WebRequest" not in result

    def test_victim_windows_template_valid_powershell(self, windows_template):
        """Output should be a valid PowerShell script."""
        result = windows_template.render()
        assert "<powershell>" in result
        assert "</powershell>" in result

    def test_victim_windows_template_explains_ssm(self, windows_template):
        """Template should explain that SSM handles setup."""
        result = windows_template.render()
        assert "SSM" in result


class TestUserDataGeneration:
    """Tests for user data generation logic."""

    def test_attacker_uses_kali_template(self, temp_templates_dir):
        """role='attacker' should use kali.sh.j2 template."""
        # NOSONAR: autoescape=False - these are shell/PowerShell templates, not HTML
        env = Environment(loader=FileSystemLoader(str(temp_templates_dir)), autoescape=False)

        # For attackers, use kali template
        role = "attacker"
        template_name = "kali.sh.j2" if role == "attacker" else "victim_linux.sh.j2"
        template = env.get_template(template_name)

        result = template.render(
            hostname="shifter-kali-42",
            public_key="ssh-ed25519 AAAA...",
        )
        assert "shifter-kali-42" in result

    def test_linux_victim_uses_linux_template(self, temp_templates_dir):
        """role='victim', os!='windows' should use victim_linux.sh.j2."""
        # NOSONAR: autoescape=False - shell/PowerShell templates, not HTML
        env = Environment(
            loader=FileSystemLoader(str(temp_templates_dir)),
            autoescape=False,
        )

        role = "victim"
        template_name = (
            "kali.sh.j2"
            if role == "attacker"
            else "victim_linux.sh.j2"
        )
        template = env.get_template(template_name)

        # Victim templates are minimal - no variables needed
        result = template.render()
        # Minimal template just logs that SSM handles setup
        assert "SSM" in result

    def test_windows_victim_uses_windows_template(self, temp_templates_dir):
        """os='windows' should use victim_windows.ps1.j2."""
        # NOSONAR: autoescape=False - shell/PowerShell templates, not HTML
        env = Environment(
            loader=FileSystemLoader(str(temp_templates_dir)),
            autoescape=False,
        )

        template_name = "victim_windows.ps1.j2"
        template = env.get_template(template_name)

        # Victim templates are minimal - no variables needed
        result = template.render()
        # Minimal template just logs that SSM handles setup
        assert "SSM" in result

    def test_user_data_base64_encoded(self, temp_templates_dir):
        """User data output should be base64 encodable."""
        # NOSONAR: autoescape=False - these are shell/PowerShell templates, not HTML
        env = Environment(loader=FileSystemLoader(str(temp_templates_dir)), autoescape=False)
        template = env.get_template("kali.sh.j2")

        script = template.render(
            hostname="shifter-kali-42",
            public_key="ssh-ed25519 AAAA...",
        )

        # Should be encodable as base64
        encoded = base64.b64encode(script.encode()).decode()
        assert len(encoded) > 0

    def test_user_data_decodes_correctly(self, temp_templates_dir):
        """Base64 encoded user data should decode back to original."""
        # NOSONAR: autoescape=False - these are shell/PowerShell templates, not HTML
        env = Environment(loader=FileSystemLoader(str(temp_templates_dir)), autoescape=False)
        template = env.get_template("kali.sh.j2")

        script = template.render(
            hostname="shifter-kali-42",
            public_key="ssh-ed25519 AAAA...",
        )

        encoded = base64.b64encode(script.encode()).decode()
        decoded = base64.b64decode(encoded).decode()

        assert decoded == script

    def test_templates_dir_env_var(self, temp_templates_dir):
        """TEMPLATES_DIR env var should be respected."""
        # This tests the pattern used in instance.py
        custom_templates_dir = str(temp_templates_dir)

        with patch.dict(os.environ, {"TEMPLATES_DIR": custom_templates_dir}):
            templates_dir = os.environ.get(
                "TEMPLATES_DIR",
                str(Path(__file__).parent.parent / "templates"),
            )
            assert templates_dir == custom_templates_dir


class TestTemplateContentSafety:
    """Tests for template content safety."""

    @pytest.fixture
    def all_templates(self):
        """Load all templates."""
        templates_dir = Path(__file__).parent.parent / "templates"
        # NOSONAR: autoescape=False - these are shell/PowerShell templates, not HTML
        env = Environment(loader=FileSystemLoader(str(templates_dir)), autoescape=False)
        return {
            "kali": env.get_template("kali.sh.j2"),
            "linux": env.get_template("victim_linux.sh.j2"),
            "windows": env.get_template("victim_windows.ps1.j2"),
        }

    def test_templates_use_strict_bash_mode(self, all_templates):
        """Linux templates should use set -euo pipefail."""
        # Kali needs hostname/public_key, victims are minimal
        kali_result = all_templates["kali"].render(
            hostname="test",
            public_key="test",
        )
        linux_result = all_templates["linux"].render()
        assert "set -euo pipefail" in kali_result or "set -e" in kali_result
        assert "set -euo pipefail" in linux_result or "set -e" in linux_result

    def test_windows_uses_error_action_stop(self, all_templates):
        """Windows template should use ErrorActionPreference Stop."""
        result = all_templates["windows"].render()
        assert 'ErrorActionPreference' in result and 'Stop' in result

    def test_templates_log_output(self, all_templates):
        """Templates should log their output for debugging."""
        # Kali needs hostname/public_key
        kali_result = all_templates["kali"].render(
            hostname="test",
            public_key="test",
        )
        assert "log" in kali_result.lower() or "echo" in kali_result.lower()

        # Victim templates are minimal
        linux_result = all_templates["linux"].render()
        windows_result = all_templates["windows"].render()
        assert "log" in linux_result.lower() or "echo" in linux_result.lower()
        assert "log" in windows_result.lower() or "Write-Host" in windows_result
