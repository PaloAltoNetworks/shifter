"""DC user data template tests for Pulumi provisioner.

Tests for the Domain Controller PowerShell template (dc_windows.ps1.j2).
Uses TDD approach - these tests are written before the template exists.
"""

import sys
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestDCTemplateExists:
    """Tests for DC template file existence."""

    def test_dc_template_exists(self):
        """DC template file should exist."""
        template_path = Path(__file__).parent.parent / "templates" / "dc_windows.ps1.j2"
        assert template_path.exists(), "dc_windows.ps1.j2 template does not exist"


class TestDCTemplateRendering:
    """Tests for DC template rendering."""

    @pytest.fixture
    def dc_template(self):
        """Load the DC template."""
        templates_dir = Path(__file__).parent.parent / "templates"
        env = Environment(loader=FileSystemLoader(str(templates_dir)), autoescape=False)
        return env.get_template("dc_windows.ps1.j2")

    @pytest.fixture
    def dc_template_context(self):
        """Standard context for DC template tests."""
        return {
            "hostname": "DC1",
            "public_key": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample test@localhost",
            "domain_name": "internal.shifter",
            "netbios_name": "SHIFTER",
            "dc_config_secret_arn": "arn:aws:secretsmanager:us-east-2:123456789012:secret:test-dc-config",
            "dsrm_password": "ComplexP@ss123!",
        }

    def test_dc_template_renders_without_error(self, dc_template, dc_template_context):
        """DC template should render with required variables."""
        result = dc_template.render(**dc_template_context)

        # Should contain AD DS installation commands
        assert "Install-WindowsFeature" in result, "Template should install Windows features"
        assert "Install-ADDSForest" in result, "Template should promote to DC"
        assert "internal.shifter" in result, "Template should include domain name"

    def test_dc_template_includes_ssh_setup(self, dc_template, dc_template_context):
        """DC template should set up SSH access like victim template."""
        result = dc_template.render(**dc_template_context)

        # SSH setup for remote access
        assert "sshd" in result, "Template should configure SSH service"
        assert "administrators_authorized_keys" in result, "Template should set up SSH key auth"

    def test_dc_template_writes_config_to_secrets_manager(
        self, dc_template, dc_template_context
    ):
        """DC template should write DC config to Secrets Manager."""
        result = dc_template.render(**dc_template_context)

        # Should write config to Secrets Manager using AWS CLI
        has_secrets_write = (
            "Write-SecretString" in result
            or "aws secretsmanager put-secret-value" in result
        )
        assert has_secrets_write, "Template should write to Secrets Manager"

        # Should reference the secret ARN
        assert (
            dc_template_context["dc_config_secret_arn"] in result
        ), "Template should use dc_config_secret_arn"

    def test_dc_template_hostname(self, dc_template, dc_template_context):
        """hostname variable should be replaced."""
        result = dc_template.render(**dc_template_context)

        assert "DC1" in result, "Hostname should appear in rendered template"
        assert "{{ hostname }}" not in result, "Jinja variable should be replaced"

    def test_dc_template_netbios_name(self, dc_template, dc_template_context):
        """netbios_name variable should be replaced."""
        result = dc_template.render(**dc_template_context)

        assert "SHIFTER" in result, "NetBIOS name should appear in rendered template"
        assert "{{ netbios_name }}" not in result, "Jinja variable should be replaced"

    def test_dc_template_valid_powershell(self, dc_template, dc_template_context):
        """Output should be a valid PowerShell script with required sections."""
        result = dc_template.render(**dc_template_context)

        # PowerShell EC2 user data format
        assert "<powershell>" in result, "Template should start with <powershell> tag"
        assert "</powershell>" in result, "Template should end with </powershell> tag"

        # Error handling
        assert "ErrorActionPreference" in result, "Template should set error handling"
        assert "Stop" in result, "Template should use strict error handling"

    def test_dc_template_configures_dns_forwarder(self, dc_template, dc_template_context):
        """DC template should configure DNS forwarder for AWS."""
        result = dc_template.render(**dc_template_context)

        # AWS VPC DNS resolver
        has_dns_forwarder = (
            "Add-DnsServerForwarder" in result or "169.254.169.253" in result
        )
        assert has_dns_forwarder, "Template should configure AWS DNS forwarder"

    def test_dc_template_generates_domain_admin_password(
        self, dc_template, dc_template_context
    ):
        """DC template should generate a domain admin password at runtime."""
        result = dc_template.render(**dc_template_context)

        # Should generate password (not hardcode it)
        has_password_gen = (
            "Get-Random" in result
            or "New-Guid" in result
            or "[System.Web.Security.Membership]::GeneratePassword" in result
            or "ConvertTo-SecureString" in result
        )
        assert has_password_gen, "Template should generate domain admin password securely"

    def test_dc_template_has_logging(self, dc_template, dc_template_context):
        """DC template should log its progress."""
        result = dc_template.render(**dc_template_context)

        # Should have logging function like victim template
        assert "Log-Message" in result or "Write-Host" in result, "Template should log progress"
