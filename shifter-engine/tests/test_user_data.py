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
    """Tests for Linux victim user data template."""

    @pytest.fixture
    def linux_template(self):
        """Load the Linux victim template."""
        templates_dir = Path(__file__).parent.parent / "templates"
        # NOSONAR: autoescape=False - these are shell/PowerShell templates, not HTML
        env = Environment(loader=FileSystemLoader(str(templates_dir)), autoescape=False)
        return env.get_template("victim_linux.sh.j2")

    def test_victim_linux_template_hostname(self, linux_template):
        """hostname variable should be replaced."""
        result = linux_template.render(
            hostname="shifter-victim-42-0",
            public_key="ssh-ed25519 AAAA...",
            presigned_url="",
            agent_s3_key="",
        )
        assert "shifter-victim-42-0" in result
        assert "{{ hostname }}" not in result

    def test_victim_linux_template_public_key(self, linux_template):
        """public_key variable should be replaced."""
        test_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample test@localhost"
        result = linux_template.render(
            hostname="shifter-victim-42-0",
            public_key=test_key,
            presigned_url="",
            agent_s3_key="",
        )
        assert test_key in result
        assert "{{ public_key }}" not in result

    def test_victim_linux_template_with_agent(self, linux_template):
        """Agent download should be included when presigned_url is provided."""
        result = linux_template.render(
            hostname="shifter-victim-42-0",
            public_key="ssh-ed25519 AAAA...",
            presigned_url="https://s3.amazonaws.com/bucket/agent.tar.gz?signed",
            agent_s3_key="agents/xdr-agent.tar.gz",
        )
        assert "curl" in result or "Downloading" in result
        assert "https://s3.amazonaws.com/bucket/agent.tar.gz?signed" in result
        assert "agents/xdr-agent.tar.gz" in result

    def test_victim_linux_template_no_agent(self, linux_template):
        """Agent section should be skipped when no presigned_url."""
        result = linux_template.render(
            hostname="shifter-victim-42-0",
            public_key="ssh-ed25519 AAAA...",
            presigned_url="",
            agent_s3_key="",
        )
        # Should have skip message, not download
        assert "No agent installer configured" in result
        assert "curl -sSf -o" not in result

    def test_victim_linux_template_valid_bash(self, linux_template):
        """Output should be a valid bash script with required sections."""
        result = linux_template.render(
            hostname="shifter-victim-42-0",
            public_key="ssh-ed25519 AAAA...",
            presigned_url="",
            agent_s3_key="",
        )
        assert result.strip().startswith("#!/bin/bash")
        # Verify essential script components rather than arbitrary length
        assert "hostnamectl set-hostname" in result  # Must set hostname
        assert "authorized_keys" in result  # Must configure SSH
        assert "echo" in result  # Must have logging/output

    def test_victim_linux_configures_ubuntu_ssh(self, linux_template):
        """Template should configure SSH for ubuntu user."""
        result = linux_template.render(
            hostname="shifter-victim-42-0",
            public_key="ssh-ed25519 AAAA...",
            presigned_url="",
            agent_s3_key="",
        )
        assert "/home/ubuntu/.ssh" in result


class TestVictimWindowsTemplate:
    """Tests for Windows victim user data template."""

    @pytest.fixture
    def windows_template(self):
        """Load the Windows victim template."""
        templates_dir = Path(__file__).parent.parent / "templates"
        # NOSONAR: autoescape=False - these are shell/PowerShell templates, not HTML
        env = Environment(loader=FileSystemLoader(str(templates_dir)), autoescape=False)
        return env.get_template("victim_windows.ps1.j2")

    def test_victim_windows_template_hostname(self, windows_template):
        """hostname variable should be replaced."""
        result = windows_template.render(
            hostname="shifter-victim-42-0",
            presigned_url="",
            agent_s3_key="",
        )
        assert "shifter-victim-42-0" in result
        assert "{{ hostname }}" not in result

    def test_victim_windows_template_with_agent(self, windows_template):
        """Agent download should be included when presigned_url is provided."""
        result = windows_template.render(
            hostname="shifter-victim-42-0",
            presigned_url="https://s3.amazonaws.com/bucket/agent.msi?signed",
            agent_s3_key="agents/xdr-agent.msi",
        )
        assert "Invoke-WebRequest" in result
        assert "https://s3.amazonaws.com/bucket/agent.msi?signed" in result

    def test_victim_windows_template_no_agent(self, windows_template):
        """Agent section should be skipped when no presigned_url."""
        result = windows_template.render(
            hostname="shifter-victim-42-0",
            presigned_url="",
            agent_s3_key="",
        )
        assert "No agent installer configured" in result

    def test_victim_windows_template_valid_powershell(self, windows_template):
        """Output should be a valid PowerShell script with required sections."""
        result = windows_template.render(
            hostname="shifter-victim-42-0",
            presigned_url="",
            agent_s3_key="",
        )
        assert "<powershell>" in result
        assert "</powershell>" in result
        # Verify essential script components rather than arbitrary length
        assert "Rename-Computer" in result  # Must set hostname
        assert "Log-Message" in result or "Write-Host" in result  # Must have logging

    def test_victim_windows_renames_computer(self, windows_template):
        """Template should rename computer."""
        result = windows_template.render(
            hostname="shifter-victim-42-0",
            presigned_url="",
            agent_s3_key="",
        )
        assert "Rename-Computer" in result


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
        # NOSONAR: autoescape=False - these are shell/PowerShell templates, not HTML
        env = Environment(loader=FileSystemLoader(str(temp_templates_dir)), autoescape=False)

        role = "victim"
        os_type = "ubuntu"
        template_name = (
            "kali.sh.j2"
            if role == "attacker"
            else ("victim_windows.ps1.j2" if os_type == "windows" else "victim_linux.sh.j2")
        )
        template = env.get_template(template_name)

        result = template.render(
            hostname="shifter-victim-42-0",
            public_key="ssh-ed25519 AAAA...",
            presigned_url="",
            agent_s3_key="",
        )
        assert "shifter-victim-42-0" in result

    def test_windows_victim_uses_windows_template(self, temp_templates_dir):
        """os='windows' should use victim_windows.ps1.j2."""
        # NOSONAR: autoescape=False - these are shell/PowerShell templates, not HTML
        env = Environment(loader=FileSystemLoader(str(temp_templates_dir)), autoescape=False)

        os_type = "windows"
        template_name = "victim_windows.ps1.j2"
        template = env.get_template(template_name)

        result = template.render(
            hostname="shifter-victim-42-0",
            presigned_url="",
            agent_s3_key="",
        )
        assert "shifter-victim-42-0" in result

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
        for name in ["kali", "linux"]:
            template = all_templates[name]
            result = template.render(
                hostname="test",
                public_key="test",
                presigned_url="",
                agent_s3_key="",
            )
            assert "set -euo pipefail" in result or "set -e" in result

    def test_windows_uses_error_action_stop(self, all_templates):
        """Windows template should use ErrorActionPreference Stop."""
        result = all_templates["windows"].render(
            hostname="test",
            presigned_url="",
            agent_s3_key="",
        )
        assert 'ErrorActionPreference' in result and 'Stop' in result

    def test_templates_log_output(self, all_templates):
        """Templates should log their output for debugging."""
        for name, template in all_templates.items():
            result = template.render(
                hostname="test",
                public_key="test" if name != "windows" else None,
                presigned_url="",
                agent_s3_key="",
            )
            # Should have some form of logging
            assert "log" in result.lower() or "echo" in result.lower() or "Write-Host" in result
