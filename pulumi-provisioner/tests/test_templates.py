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
        # NOSONAR: autoescape=False is intentional - these are PowerShell templates, not HTML
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
            "dc_config_param_name": "/shifter/dev/range/42/dc-config",
            "dsrm_password": "TestDsrmP@ss!",  # nosec B105 - test fixture
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

    def test_dc_template_writes_config_to_ssm_parameter(
        self, dc_template, dc_template_context
    ):
        """DC template should write DC config to SSM Parameter Store."""
        result = dc_template.render(**dc_template_context)

        # Should write config to SSM Parameter Store using AWS CLI
        assert "aws ssm put-parameter" in result, "Template should use aws ssm put-parameter"

        # Should use SecureString type for encryption
        assert "--type SecureString" in result, "Template should use SecureString type"

        # Should use --overwrite for idempotent updates
        assert "--overwrite" in result, "Template should use --overwrite flag"

        # Should reference the parameter name
        assert (
            dc_template_context["dc_config_param_name"] in result
        ), "Template should use dc_config_param_name"

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


# =============================================================================
# Domain Member Template Tests (Phase 7)
# =============================================================================


class TestDomainMemberTemplateExists:
    """Tests for domain member template file existence."""

    def test_domain_member_template_exists(self):
        """Domain member template file should exist."""
        template_path = (
            Path(__file__).parent.parent / "templates" / "domain_member_windows.ps1.j2"
        )
        assert template_path.exists(), "domain_member_windows.ps1.j2 template does not exist"


class TestDomainMemberTemplateRendering:
    """Tests for domain member template rendering."""

    @pytest.fixture
    def domain_member_template(self):
        """Load the domain member template."""
        templates_dir = Path(__file__).parent.parent / "templates"
        # NOSONAR: autoescape=False is intentional - these are PowerShell templates, not HTML
        env = Environment(loader=FileSystemLoader(str(templates_dir)), autoescape=False)
        return env.get_template("domain_member_windows.ps1.j2")

    @pytest.fixture
    def domain_member_context(self):
        """Standard context for domain member template tests."""
        return {
            "hostname": "WORKSTATION1",
            "public_key": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample test@localhost",
            "dc_config_param_name": "/shifter/dev/range/42/dc-config",
            "presigned_url": "https://s3.amazonaws.com/bucket/agent.msi?signature=xxx",
            "agent_s3_key": "agents/xdr-agent.msi",
        }

    def test_domain_member_template_renders_without_error(
        self, domain_member_template, domain_member_context
    ):
        """Domain member template should render with required variables."""
        result = domain_member_template.render(**domain_member_context)

        # Should be valid PowerShell
        assert "<powershell>" in result, "Template should start with <powershell> tag"
        assert "</powershell>" in result, "Template should end with </powershell> tag"

    def test_domain_member_reads_dc_config_from_ssm(
        self, domain_member_template, domain_member_context
    ):
        """Domain member should read DC config from SSM Parameter Store."""
        result = domain_member_template.render(**domain_member_context)

        # Should read from SSM using AWS CLI
        assert "aws ssm get-parameter" in result, "Template should use aws ssm get-parameter"

        # Should use --with-decryption for SecureString
        assert "--with-decryption" in result, "Template should decrypt SecureString"

        # Should reference the DC config parameter name
        assert (
            domain_member_context["dc_config_param_name"] in result
        ), "Template should use dc_config_param_name"

    def test_domain_member_has_retry_logic(
        self, domain_member_template, domain_member_context
    ):
        """Domain member should retry reading DC config (DC might not be ready yet)."""
        result = domain_member_template.render(**domain_member_context)

        # Should have bounded retry logic
        has_retry = (
            "while" in result.lower()
            or "attempt" in result.lower()
            or "retry" in result.lower()
        )
        assert has_retry, "Template should have retry logic for DC readiness"

        # Should have max attempts to prevent infinite loop
        has_bounded = "maxAttempts" in result or "max" in result.lower()
        assert has_bounded, "Template should have bounded retry attempts"

    def test_domain_member_sets_dns_to_dc(
        self, domain_member_template, domain_member_context
    ):
        """Domain member should set DNS to DC IP before joining."""
        result = domain_member_template.render(**domain_member_context)

        # Should configure DNS client
        assert (
            "Set-DnsClientServerAddress" in result or "DnsClientServerAddress" in result
        ), "Template should set DNS to DC IP"

    def test_domain_member_joins_domain(
        self, domain_member_template, domain_member_context
    ):
        """Domain member should join the domain using Add-Computer."""
        result = domain_member_template.render(**domain_member_context)

        # Should use Add-Computer cmdlet
        assert "Add-Computer" in result, "Template should use Add-Computer to join domain"

        # Should use -DomainName parameter
        assert "-DomainName" in result, "Template should specify domain name"

        # Should use -Credential parameter
        assert "-Credential" in result, "Template should use credentials"

    def test_domain_member_installs_agent_after_reboot(
        self, domain_member_template, domain_member_context
    ):
        """Domain member should schedule agent install for after reboot."""
        result = domain_member_template.render(**domain_member_context)

        # Should have scheduled task for post-reboot
        has_scheduled_task = (
            "ScheduledTask" in result
            or "Register-ScheduledTask" in result
            or "New-ScheduledTask" in result
        )
        assert has_scheduled_task, "Template should schedule post-reboot task"

        # Should reference the agent presigned URL
        assert (
            "presigned_url" in result.lower()
            or domain_member_context["presigned_url"] in result
            or "Invoke-WebRequest" in result
        ), "Template should download agent"

    def test_domain_member_reboots_after_join(
        self, domain_member_template, domain_member_context
    ):
        """Domain member should reboot after joining domain."""
        result = domain_member_template.render(**domain_member_context)

        # Should have reboot command (Restart-Computer, shutdown, or -Restart flag on Add-Computer)
        assert (
            "Restart-Computer" in result
            or "shutdown" in result.lower()
            or "-Restart" in result
        ), "Template should reboot after domain join"

    def test_domain_member_has_ssh_setup(
        self, domain_member_template, domain_member_context
    ):
        """Domain member should set up SSH access like other templates."""
        result = domain_member_template.render(**domain_member_context)

        # SSH setup for remote access
        assert "sshd" in result, "Template should configure SSH service"
        assert (
            "administrators_authorized_keys" in result
        ), "Template should set up SSH key auth"

    def test_domain_member_has_error_handling(
        self, domain_member_template, domain_member_context
    ):
        """Domain member template should have proper error handling."""
        result = domain_member_template.render(**domain_member_context)

        # Error handling
        assert "ErrorActionPreference" in result, "Template should set error handling"
        assert "Stop" in result, "Template should use strict error handling"
        assert "catch" in result.lower(), "Template should have try-catch"

    def test_domain_member_has_logging(
        self, domain_member_template, domain_member_context
    ):
        """Domain member template should log its progress."""
        result = domain_member_template.render(**domain_member_context)

        # Should have logging
        assert (
            "Log-Message" in result or "Write-Host" in result
        ), "Template should log progress"

    def test_domain_member_hostname(
        self, domain_member_template, domain_member_context
    ):
        """hostname variable should be replaced."""
        result = domain_member_template.render(**domain_member_context)

        assert "WORKSTATION1" in result, "Hostname should appear in rendered template"
        assert "{{ hostname }}" not in result, "Jinja variable should be replaced"

    def test_domain_member_no_agent_url_skips_install(self, domain_member_template):
        """Domain member without agent URL should skip agent installation."""
        context = {
            "hostname": "WORKSTATION1",
            "public_key": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample test@localhost",
            "dc_config_param_name": "/shifter/dev/range/42/dc-config",
            "presigned_url": "",  # No agent
            "agent_s3_key": "",
        }
        result = domain_member_template.render(**context)

        # Should still work (domain join is primary function)
        assert "Add-Computer" in result, "Template should still join domain"


# =============================================================================
# DC Template SSM Parameter JSON Structure Tests
# =============================================================================


class TestDCConfigJsonStructure:
    """Tests for DC config JSON structure written to SSM.

    The DC writes a JSON object to SSM that domain members read.
    These tests verify all required fields are present in the JSON.
    """

    @pytest.fixture
    def dc_template(self):
        """Load the DC template."""
        templates_dir = Path(__file__).parent.parent / "templates"
        # NOSONAR: autoescape=False is intentional - these are PowerShell templates, not HTML
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
            "dc_config_param_name": "/shifter/dev/range/42/dc-config",
            "dsrm_password": "TestDsrmP@ss!",  # nosec B105 - test fixture
        }

    def test_dc_config_includes_domain_name(self, dc_template, dc_template_context):
        """DC config JSON must include domain_name field."""
        result = dc_template.render(**dc_template_context)

        # The JSON object being built should include domain_name
        assert "domain_name" in result, "DC config JSON must include domain_name field"

    def test_dc_config_includes_netbios_name(self, dc_template, dc_template_context):
        """DC config JSON must include netbios_name field."""
        result = dc_template.render(**dc_template_context)

        assert "netbios_name" in result, "DC config JSON must include netbios_name field"

    def test_dc_config_includes_dc_ip(self, dc_template, dc_template_context):
        """DC config JSON must include dc_ip field."""
        result = dc_template.render(**dc_template_context)

        assert "dc_ip" in result, "DC config JSON must include dc_ip field"

    def test_dc_config_includes_domain_admin_password(self, dc_template, dc_template_context):
        """DC config JSON must include domain_admin_password field."""
        result = dc_template.render(**dc_template_context)

        assert "domain_admin_password" in result, "DC config JSON must include domain_admin_password"

    def test_dc_config_includes_domain_admin_username(self, dc_template, dc_template_context):
        """DC config JSON must include domain_admin_username field."""
        result = dc_template.render(**dc_template_context)

        assert "domain_admin_username" in result, "DC config JSON must include domain_admin_username"

    def test_dc_config_uses_convert_to_json(self, dc_template, dc_template_context):
        """DC config should use ConvertTo-Json for proper JSON serialization."""
        result = dc_template.render(**dc_template_context)

        assert "ConvertTo-Json" in result, "DC config must use ConvertTo-Json for serialization"


# =============================================================================
# Domain Member Template Command Ordering Tests
# =============================================================================


class TestDomainMemberCommandOrdering:
    """Tests for critical command ordering in domain member template.

    The order of operations matters:
    1. SSH setup (early, for debugging access)
    2. Read DC config from SSM (with retry)
    3. Set DNS to DC IP (required before domain join)
    4. Schedule post-reboot agent task (before domain join triggers reboot)
    5. Join domain with Add-Computer -Restart (LAST, triggers reboot)

    If these are out of order, domain join will fail.
    """

    @pytest.fixture
    def domain_member_template(self):
        """Load the domain member template."""
        templates_dir = Path(__file__).parent.parent / "templates"
        # NOSONAR: autoescape=False is intentional - these are PowerShell templates, not HTML
        env = Environment(loader=FileSystemLoader(str(templates_dir)), autoescape=False)
        return env.get_template("domain_member_windows.ps1.j2")

    @pytest.fixture
    def domain_member_context(self):
        """Standard context for domain member template tests."""
        return {
            "hostname": "WORKSTATION1",
            "public_key": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample test@localhost",
            "dc_config_param_name": "/shifter/dev/range/42/dc-config",
            "presigned_url": "https://s3.amazonaws.com/bucket/agent.msi?signature=xxx",
            "agent_s3_key": "agents/xdr-agent.msi",
        }

    def test_dns_set_before_domain_join(
        self, domain_member_template, domain_member_context
    ):
        """DNS must be configured BEFORE Add-Computer (domain join requires DNS)."""
        result = domain_member_template.render(**domain_member_context)

        dns_pos = result.find("Set-DnsClientServerAddress")
        join_pos = result.find("Add-Computer")

        assert dns_pos != -1, "Template must set DNS"
        assert join_pos != -1, "Template must join domain"
        assert dns_pos < join_pos, "DNS must be configured BEFORE domain join"

    def test_dc_config_read_before_dns_set(
        self, domain_member_template, domain_member_context
    ):
        """DC config must be read from SSM BEFORE setting DNS (need DC IP)."""
        result = domain_member_template.render(**domain_member_context)

        ssm_pos = result.find("aws ssm get-parameter")
        dns_pos = result.find("Set-DnsClientServerAddress")

        assert ssm_pos != -1, "Template must read DC config from SSM"
        assert dns_pos != -1, "Template must set DNS"
        assert ssm_pos < dns_pos, "SSM read must happen BEFORE DNS configuration"

    def test_scheduled_task_before_domain_join(
        self, domain_member_template, domain_member_context
    ):
        """Scheduled task must be registered BEFORE Add-Computer (join triggers reboot)."""
        result = domain_member_template.render(**domain_member_context)

        task_pos = result.find("Register-ScheduledTask")
        join_pos = result.find("Add-Computer")

        assert task_pos != -1, "Template must register scheduled task"
        assert join_pos != -1, "Template must join domain"
        assert task_pos < join_pos, "Scheduled task must be registered BEFORE domain join"

    def test_ssh_setup_before_dc_config_read(
        self, domain_member_template, domain_member_context
    ):
        """SSH should be configured early for debugging access if later steps fail."""
        result = domain_member_template.render(**domain_member_context)

        ssh_pos = result.find("Start-Service sshd")
        ssm_pos = result.find("aws ssm get-parameter")

        assert ssh_pos != -1, "Template must start SSH service"
        assert ssm_pos != -1, "Template must read DC config"
        assert ssh_pos < ssm_pos, "SSH should be set up early for debugging"

    def test_add_computer_is_last_operation(
        self, domain_member_template, domain_member_context
    ):
        """Add-Computer with -Restart must be the final operation (triggers reboot)."""
        result = domain_member_template.render(**domain_member_context)

        join_pos = result.find("Add-Computer")
        end_pos = result.find("</powershell>")

        # Find any other significant operations after Add-Computer
        after_join = result[join_pos:end_pos]

        # The only things after Add-Computer should be:
        # - The rest of the Add-Computer command itself
        # - Comments
        # - Closing braces for try/catch
        # - Empty lines

        # Check that there's no other major operation
        forbidden_after = [
            "Invoke-WebRequest",  # No downloads after join
            "Set-DnsClientServerAddress",  # No DNS changes after join
            "Register-ScheduledTask",  # No new tasks after join
            "aws ssm",  # No SSM operations after join
        ]

        for forbidden in forbidden_after:
            # Skip if it's part of the Add-Computer line or in a comment
            remaining = result[join_pos + len("Add-Computer"):end_pos]
            if forbidden in remaining:
                # Check if it's in a comment context (rough check)
                forbidden_pos = remaining.find(forbidden)
                line_start = remaining.rfind("\n", 0, forbidden_pos)
                line = remaining[line_start:forbidden_pos]
                if "#" not in line and "Note:" not in line:
                    pytest.fail(f"'{forbidden}' should not appear after Add-Computer")

    def test_domain_join_uses_restart_flag(
        self, domain_member_template, domain_member_context
    ):
        """Add-Computer must use -Restart flag to trigger reboot."""
        result = domain_member_template.render(**domain_member_context)

        # Find the Add-Computer command and verify -Restart is present
        join_pos = result.find("Add-Computer")
        assert join_pos != -1, "Template must have Add-Computer"

        # Look at the Add-Computer command block (next ~200 chars)
        add_computer_block = result[join_pos:join_pos + 200]
        assert "-Restart" in add_computer_block, "Add-Computer must use -Restart flag"
