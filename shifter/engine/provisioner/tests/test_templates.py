"""DC user data template tests for Shifter Engine.

Tests for:
- Domain Controller PowerShell template (dc_windows.ps1.j2)
- NGFW init-cfg.txt template (ngfw_init_cfg.txt.j2)

NOTE: The DC template is now a minimal bootstrap script (hostname, SSH).
AD DS installation is handled via SSM Run Command orchestration.
See test_dc_setup_plan.py for AD DS setup tests.
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
    """Tests for DC user_data template rendering.

    ARCHITECTURE NOTE: DC user_data is intentionally minimal.
    All setup (hostname, SSH, AD DS) is handled via SSM Run Command orchestration:
    - BootstrapPlan: hostname + SSH + reboot
    - DCSetupPlan: AD DS install + promote

    See test_bootstrap_plan.py and test_dc_setup_plan.py for setup tests.
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
        """Standard context for DC template tests (may be empty - template is minimal)."""
        return {}

    def test_dc_template_renders_without_error(self, dc_template, dc_template_context):
        """DC template should render successfully."""
        result = dc_template.render(**dc_template_context)

        # Template is minimal - just logs that SSM will handle setup
        assert "SSM" in result, "Template should mention SSM orchestration"
        assert "<powershell>" in result, "Template should have PowerShell tags"

    def test_dc_template_valid_powershell(self, dc_template, dc_template_context):
        """Output should be valid PowerShell with proper tags."""
        result = dc_template.render(**dc_template_context)

        # PowerShell EC2 user data format
        assert "<powershell>" in result, "Template should start with <powershell> tag"
        assert "</powershell>" in result, "Template should end with </powershell> tag"

    def test_dc_template_has_logging(self, dc_template, dc_template_context):
        """DC template should log that instance started."""
        result = dc_template.render(**dc_template_context)

        # Minimal logging - just indicates SSM will take over
        assert "Out-File" in result or "Write-Host" in result, "Template should log startup"

    def test_dc_template_no_setup_logic(self, dc_template, dc_template_context):
        """DC template should NOT do any setup (SSM handles everything)."""
        result = dc_template.render(**dc_template_context)

        # Setup is via SSM orchestration, not user data
        assert "Rename-Computer" not in result, "Hostname set via SSM BootstrapPlan"
        assert "Start-Service sshd" not in result, "SSH configured via SSM BootstrapPlan"
        assert "Install-WindowsFeature" not in result, "AD DS installed via SSM DCSetupPlan"
        assert "Install-ADDSForest" not in result, "DC promotion via SSM DCSetupPlan"

    def test_dc_template_no_template_variables(self, dc_template, dc_template_context):
        """DC template should not require any template variables (minimal bootstrap)."""
        # Template should render with empty context
        result = dc_template.render()
        assert result, "Template should render with no context"
        assert "{{" not in result, "No unrendered template variables"


class TestNGFWInitCfgTemplate:
    """Tests for NGFW init-cfg.txt template (SCM-based bootstrap).

    The init-cfg.txt is placed in S3 and read by VM-Series at boot time.
    It configures SCM registration using PIN-based authentication.
    """

    @pytest.fixture
    def init_cfg_template(self):
        """Load the init-cfg template."""
        templates_dir = Path(__file__).parent.parent / "templates"
        env = Environment(loader=FileSystemLoader(str(templates_dir)), autoescape=False)
        return env.get_template("ngfw_init_cfg.txt.j2")

    @pytest.fixture
    def scm_context(self):
        """Standard context for SCM-based init-cfg template."""
        return {
            "hostname": "ngfw-range42",
            "pin_id": "abc123-pin-id",
            "pin_value": "xyz789-secret-value",
            "folder_name": "Edwards-Lab",
        }

    def test_init_cfg_template_exists(self):
        """Init-cfg template file should exist."""
        template_path = Path(__file__).parent.parent / "templates" / "ngfw_init_cfg.txt.j2"
        assert template_path.exists(), "ngfw_init_cfg.txt.j2 template does not exist"

    def test_init_cfg_renders_without_error(self, init_cfg_template, scm_context):
        """Init-cfg template should render successfully with SCM context."""
        result = init_cfg_template.render(**scm_context)
        assert result, "Template should produce output"

    def test_init_cfg_uses_dhcp_client(self, init_cfg_template, scm_context):
        """Init-cfg should configure DHCP client for network."""
        result = init_cfg_template.render(**scm_context)
        assert "type=dhcp-client" in result

    def test_init_cfg_sets_hostname(self, init_cfg_template, scm_context):
        """Init-cfg should set the hostname from context."""
        result = init_cfg_template.render(**scm_context)
        assert "hostname=ngfw-range42" in result

    def test_init_cfg_uses_panorama_cloud(self, init_cfg_template, scm_context):
        """Init-cfg should set panorama-server=cloud for SCM."""
        result = init_cfg_template.render(**scm_context)
        assert "panorama-server=cloud" in result

    def test_init_cfg_has_pin_id(self, init_cfg_template, scm_context):
        """Init-cfg should include vm-series-auto-registration-pin-id."""
        result = init_cfg_template.render(**scm_context)
        assert "vm-series-auto-registration-pin-id=abc123-pin-id" in result

    def test_init_cfg_has_pin_value(self, init_cfg_template, scm_context):
        """Init-cfg should include vm-series-auto-registration-pin-value."""
        result = init_cfg_template.render(**scm_context)
        assert "vm-series-auto-registration-pin-value=xyz789-secret-value" in result

    def test_init_cfg_has_dgname_folder(self, init_cfg_template, scm_context):
        """Init-cfg should set dgname to the SCM folder name."""
        result = init_cfg_template.render(**scm_context)
        assert "dgname=Edwards-Lab" in result

    def test_init_cfg_no_vm_auth_key(self, init_cfg_template, scm_context):
        """Init-cfg should NOT use vm-auth-key (that's Panorama, not SCM)."""
        result = init_cfg_template.render(**scm_context)
        assert "vm-auth-key" not in result

    def test_init_cfg_no_tplname(self, init_cfg_template, scm_context):
        """Init-cfg should NOT use tplname (that's Panorama template stack)."""
        result = init_cfg_template.render(**scm_context)
        assert "tplname" not in result

    def test_init_cfg_preserves_special_chars_in_pin(self, init_cfg_template):
        """Special characters in PIN values should be preserved."""
        context = {
            "hostname": "ngfw-test",
            "pin_id": "pin+with/special=chars",
            "pin_value": "secret!@#$%",
            "folder_name": "Folder-With_Dots.Here",
        }
        result = init_cfg_template.render(**context)
        assert "pin+with/special=chars" in result
        assert "secret!@#$%" in result
        assert "Folder-With_Dots.Here" in result
