"""
Tests for Packer AMI build configuration.

Run with: pytest shifter/packer/tests/test_packer.py -v
"""

import shutil
import subprocess
from pathlib import Path

import pytest

PACKER_DIR = Path(__file__).parent.parent
SCRIPTS_DIR = PACKER_DIR / "scripts"
REPO_ROOT = PACKER_DIR.parent.parent
PACKER_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "packer.yml"


class TestScriptStructure:
    """Test that all required scripts exist and have correct structure."""

    @pytest.fixture
    def kali_scripts(self):
        return list((SCRIPTS_DIR / "kali").glob("*.sh"))

    @pytest.fixture
    def ubuntu_scripts(self):
        return list((SCRIPTS_DIR / "ubuntu").glob("*.sh"))

    @pytest.fixture
    def common_scripts(self):
        return list((SCRIPTS_DIR / "common").glob("*.sh"))

    @pytest.fixture
    def brokenbk_scripts(self):
        return list((SCRIPTS_DIR / "brokenbk").glob("*.sh"))

    def test_kali_scripts_exist(self, kali_scripts):
        """Kali directory should have scripts."""
        assert len(kali_scripts) >= 3, "Expected at least 3 kali scripts"

    def test_ubuntu_scripts_exist(self, ubuntu_scripts):
        """Ubuntu directory should have scripts."""
        assert len(ubuntu_scripts) >= 4, "Expected at least 4 ubuntu scripts"

    def test_common_scripts_exist(self, common_scripts):
        """Common directory should have cleanup script."""
        assert len(common_scripts) >= 1, "Expected at least 1 common script"

    def test_required_kali_scripts(self):
        """Check all required Kali scripts exist."""
        required = ["base.sh", "tools.sh", "claude-code.sh"]
        for script in required:
            path = SCRIPTS_DIR / "kali" / script
            assert path.exists(), f"Missing required script: {script}"

    def test_required_ubuntu_scripts(self):
        """Check all required Ubuntu scripts exist."""
        required = ["base.sh", "services.sh", "tools.sh", "claude-code.sh"]
        for script in required:
            path = SCRIPTS_DIR / "ubuntu" / script
            assert path.exists(), f"Missing required Ubuntu script: {script}"

    def test_brokenbk_scripts_exist(self, brokenbk_scripts):
        """Brokenbk directory should have scripts."""
        assert len(brokenbk_scripts) >= 2, "Expected at least 2 brokenbk scripts"

    def test_required_brokenbk_scripts(self):
        """Check all required Broken Bank scripts exist (referenced by brokenbk.pkr.hcl)."""
        required = ["base.sh", "app.sh"]
        for script in required:
            path = SCRIPTS_DIR / "brokenbk" / script
            assert path.exists(), f"Missing required brokenbk script: {script}"

    def test_cleanup_script_exists(self):
        """Cleanup script should exist."""
        assert (SCRIPTS_DIR / "common" / "cleanup.sh").exists()


class TestScriptContent:
    """Test script content for best practices."""

    @pytest.fixture
    def all_scripts(self):
        scripts = []
        for pattern in ["kali/*.sh", "ubuntu/*.sh", "brokenbk/*.sh", "common/*.sh"]:
            scripts.extend(SCRIPTS_DIR.glob(pattern))
        return scripts

    def test_shebang(self, all_scripts):
        """All scripts should have bash shebang."""
        for script in all_scripts:
            content = script.read_text()
            assert content.startswith("#!/bin/bash"), f"{script.name} missing shebang"

    def test_strict_mode(self, all_scripts):
        """All scripts should use strict mode."""
        for script in all_scripts:
            content = script.read_text()
            assert "set -euo pipefail" in content, f"{script.name} missing strict mode"

    def test_no_hardcoded_passwords(self, all_scripts):
        """Scripts should not contain hardcoded passwords."""
        suspicious_patterns = [
            "password=",
            "PASSWORD=",
            "secret=",
            "SECRET=",
            "api_key=",
            "API_KEY=",
        ]
        for script in all_scripts:
            content = script.read_text().lower()
            for pattern in suspicious_patterns:
                # Allow environment variable references
                if pattern.lower() in content:
                    # Check if it's just a variable reference, not a value assignment
                    lines = [
                        line
                        for line in content.split("\n")
                        if pattern.lower() in line and "=$" not in line and '=""' not in line
                    ]
                    assert not any("=" in line and not line.strip().startswith("#") for line in lines), (
                        f"{script.name} may contain hardcoded secret: {pattern}"
                    )

    def test_noninteractive_apt(self, all_scripts):
        """Scripts using apt should be non-interactive."""
        for script in all_scripts:
            content = script.read_text()
            if "apt-get install" in content:
                has_noninteractive = "DEBIAN_FRONTEND=noninteractive" in content or "apt-get install -y" in content
                assert has_noninteractive, f"{script.name} may hang on apt prompts"


class TestPackerTemplates:
    """Test Packer HCL templates."""

    @pytest.fixture
    def templates(self):
        return list(PACKER_DIR.glob("*.pkr.hcl"))

    def test_templates_exist(self, templates):
        """At least one Packer template should exist."""
        assert len(templates) >= 1, "No Packer templates found"

    def test_kali_template_exists(self):
        """Kali template should exist."""
        assert (PACKER_DIR / "kali.pkr.hcl").exists()

    def test_ubuntu_template_exists(self):
        """Ubuntu template should exist."""
        assert (PACKER_DIR / "ubuntu.pkr.hcl").exists()

    def test_brokenbk_template_exists(self):
        """Broken Bank template should exist."""
        assert (PACKER_DIR / "brokenbk.pkr.hcl").exists()

    def test_variables_file_exists(self):
        """Variables file should exist."""
        assert (PACKER_DIR / "variables.pkr.hcl").exists()

    @pytest.mark.skipif(
        shutil.which("packer") is None,
        reason="Packer not installed",
    )
    def test_packer_validate(self):
        """Packer templates should be valid."""
        packer_path = shutil.which("packer")

        # Pass cwd= rather than os.chdir() so the validate runs in PACKER_DIR
        # without mutating the process-global working directory for the rest
        # of the pytest session.
        # Init first
        # Security context: packer_path from shutil.which() in controlled test environment
        subprocess.run([packer_path, "init", "."], capture_output=True, cwd=PACKER_DIR)  # noqa: S603

        # Validate with var-file (no defaults)
        result = subprocess.run(  # noqa: S603
            [packer_path, "validate", "-var-file=dev.pkrvars.hcl", "."],
            capture_output=True,
            text=True,
            cwd=PACKER_DIR,
        )
        assert result.returncode == 0, f"Packer validate failed: {result.stderr}"


class TestKaliTools:
    """Test that Kali tools script includes required packages."""

    @pytest.fixture
    def tools_content(self):
        return (SCRIPTS_DIR / "kali" / "tools.sh").read_text()

    def test_sshpass_included(self, tools_content):
        """sshpass should be installed for non-interactive SSH."""
        assert "sshpass" in tools_content

    def test_kali_metapackage(self, tools_content):
        """Kali headless metapackage should be installed."""
        assert "kali-linux-headless" in tools_content


class TestClaudeCode:
    """Test Claude Code installation script."""

    @pytest.fixture
    def claude_content(self):
        return (SCRIPTS_DIR / "kali" / "claude-code.sh").read_text()

    def test_npm_install(self, claude_content):
        """Claude Code should be installed via npm."""
        assert "npm install" in claude_content
        assert "claude-code" in claude_content

    def test_bedrock_config(self, claude_content):
        """Bedrock environment variables should be set."""
        assert "CLAUDE_CODE_USE_BEDROCK=1" in claude_content
        assert "AWS_REGION" in claude_content

    def test_kali_user_bashrc(self, claude_content):
        """Mission Control SSH uses the kali user."""
        assert "/home/kali/.bashrc" in claude_content

    def test_autostart_installer(self, claude_content):
        """Kali bake should install the shared autostart hook."""
        assert "/usr/local/lib/shifter/claude-autostart-install.sh" in claude_content
        assert "install_claude_autostart /home/kali/.bashrc" in claude_content


class TestClaudeAutostartInstall:
    """Test shared Claude autostart installer (#180)."""

    @pytest.fixture
    def autostart_content(self):
        return (SCRIPTS_DIR / "common" / "claude-autostart-install.sh").read_text()

    def test_installer_exists(self):
        assert (SCRIPTS_DIR / "common" / "claude-autostart-install.sh").exists()

    def test_canonical_command(self, autostart_content):
        assert "claude --dangerously-skip-permissions" in autostart_content

    def test_interactive_guards(self, autostart_content):
        assert "[[ $- != *i* ]]" in autostart_content
        assert "[[ ! -t 0 ]]" in autostart_content
        assert "SHIFTER_CLAUDE_AUTOSTART_DONE" in autostart_content

    def test_expected_users_only(self, autostart_content):
        assert "kali|ubuntu" in autostart_content

    def test_no_exec(self, autostart_content):
        assert "exec claude" not in autostart_content


class TestCleanup:
    """Test cleanup script."""

    @pytest.fixture
    def cleanup_content(self):
        return (SCRIPTS_DIR / "common" / "cleanup.sh").read_text()

    def test_apt_clean(self, cleanup_content):
        """Cleanup should clear apt cache."""
        assert "apt-get clean" in cleanup_content

    def test_clear_bash_history(self, cleanup_content):
        """Cleanup should clear bash history."""
        assert "bash_history" in cleanup_content.lower()

    def test_clear_ssh_keys(self, cleanup_content):
        """Cleanup should remove SSH host keys."""
        assert "ssh_host_" in cleanup_content


class TestUbuntuServices:
    """Test that Ubuntu services script includes required services."""

    @pytest.fixture
    def services_content(self):
        return (SCRIPTS_DIR / "ubuntu" / "services.sh").read_text()

    def test_apache_included(self, services_content):
        """Apache with PHP should be installed."""
        assert "apache2" in services_content
        assert "libapache2-mod-php" in services_content

    def test_mysql_included(self, services_content):
        """MySQL should be installed."""
        assert "mysql-server" in services_content

    def test_docker_included(self, services_content):
        """Docker should be installed."""
        assert "docker" in services_content

    def test_openssh_included(self, services_content):
        """OpenSSH Server should be installed."""
        assert "openssh-server" in services_content

    def test_vsftpd_included(self, services_content):
        """vsftpd should be installed."""
        assert "vsftpd" in services_content

    def test_samba_included(self, services_content):
        """Samba should be installed (but not enabled)."""
        assert "samba" in services_content

    def test_services_enabled(self, services_content):
        """Required services should be enabled."""
        assert "systemctl enable apache2" in services_content
        assert "systemctl enable mysql" in services_content
        assert "systemctl enable docker" in services_content
        assert "systemctl enable ssh" in services_content
        assert "systemctl enable vsftpd" in services_content


class TestUbuntuTools:
    """Test that Ubuntu tools script includes required packages."""

    @pytest.fixture
    def tools_content(self):
        return (SCRIPTS_DIR / "ubuntu" / "tools.sh").read_text()

    def test_build_essential(self, tools_content):
        """build-essential should be installed."""
        assert "build-essential" in tools_content

    def test_python3_included(self, tools_content):
        """Python 3 with pip and venv should be installed."""
        assert "python3" in tools_content
        assert "python3-pip" in tools_content
        assert "python3-venv" in tools_content

    def test_nodejs_included(self, tools_content):
        """Node.js 20.x should be installed."""
        assert "nodejs" in tools_content
        assert "setup_20" in tools_content

    def test_git_included(self, tools_content):
        """Git should be installed."""
        assert "git" in tools_content

    def test_basic_tools_included(self, tools_content):
        """Basic tools should be installed."""
        assert "curl" in tools_content
        assert "nano" in tools_content
        assert "netcat" in tools_content


class TestUbuntuClaudeCode:
    """Test Ubuntu Claude Code installation script."""

    @pytest.fixture
    def claude_content(self):
        return (SCRIPTS_DIR / "ubuntu" / "claude-code.sh").read_text()

    def test_npm_install(self, claude_content):
        """Claude Code should be installed via npm."""
        assert "npm install" in claude_content
        assert "claude-code" in claude_content

    def test_bedrock_config(self, claude_content):
        """Bedrock environment variables should be set."""
        assert "CLAUDE_CODE_USE_BEDROCK=1" in claude_content
        assert "AWS_REGION" in claude_content

    def test_autostart_installer(self, claude_content):
        """Ubuntu victim bake should install the shared autostart hook."""
        assert "/usr/local/lib/shifter/claude-autostart-install.sh" in claude_content
        assert "install_claude_autostart /home/ubuntu/.bashrc" in claude_content


class TestWindowsServices:
    """Test that Windows services.ps1 has correct XAMPP install invocation."""

    @pytest.fixture
    def services_content(self):
        return (SCRIPTS_DIR / "windows" / "services.ps1").read_text()

    def test_no_launchapps_arg(self, services_content):
        """--launchapps is not a supported XAMPP unattended arg and must be absent."""
        assert "--launchapps" not in services_content

    def test_unattended_mode_present(self, services_content):
        """XAMPP installer must be called with --mode unattended."""
        assert "--mode unattended" in services_content

    def test_passhru_used(self, services_content):
        """Start-Process for XAMPP must capture the process object via -PassThru."""
        assert "-PassThru" in services_content

    def test_exitcode_guard(self, services_content):
        """Script must check XAMPP exit code and call exit 1 on failure."""
        assert "ExitCode" in services_content
        assert "exit 1" in services_content


class TestBuilderLifecycle:
    """Regression tests for transient EC2 builder termination (issue #342)."""

    LINUX_SOURCES = ("kali", "ubuntu", "brokenbk")
    WINDOWS_SOURCES = ("windows", "dc")

    @staticmethod
    def _template_content(source: str) -> str:
        path = PACKER_DIR / f"{source}.pkr.hcl"
        assert path.exists(), f"Missing template: {path.name}"
        return path.read_text()

    @pytest.mark.parametrize("source", LINUX_SOURCES)
    def test_linux_shutdown_behavior_terminates(self, source):
        """Linux builders must terminate on shutdown so orphaned instances do not incur cost."""
        content = self._template_content(source)
        assert 'shutdown_behavior = "terminate"' in content

    @pytest.mark.parametrize("source", WINDOWS_SOURCES)
    def test_windows_shutdown_behavior_stops_for_sysprep(self, source):
        """Windows builders stop (not terminate) so Packer can snapshot the sysprep image."""
        content = self._template_content(source)
        assert 'shutdown_behavior = "stop"' in content
        assert "disable_stop_instance = true" in content

    @pytest.mark.parametrize(
        ("source", "builder_name"),
        [
            ("kali", "packer-builder-kali"),
            ("ubuntu", "packer-builder-ubuntu"),
            ("brokenbk", "packer-builder-brokenbk"),
            ("windows", "packer-builder-windows"),
            ("dc", "packer-builder-dc"),
        ],
    )
    def test_run_tags_name_matches_workflow_cleanup_selector(self, source, builder_name):
        """Workflow cleanup keys off Packer run_tags.Name; templates must stay aligned."""
        content = self._template_content(source)
        assert f'Name = "{builder_name}"' in content


class TestPackerWorkflowCleanup:
    """Workflow invariants for defensive builder cleanup after Packer runs."""

    CLEANUP_STEP_NAME = "- name: Cleanup Packer builder instances"

    @staticmethod
    def _cleanup_step_body(workflow_content: str) -> str:
        cleanup_idx = workflow_content.index(TestPackerWorkflowCleanup.CLEANUP_STEP_NAME)
        next_step_idx = workflow_content.find("\n      - name:", cleanup_idx + 1)
        if next_step_idx == -1:
            return workflow_content[cleanup_idx:]
        return workflow_content[cleanup_idx:next_step_idx]

    @pytest.fixture
    def workflow_content(self):
        assert PACKER_WORKFLOW.exists(), "packer.yml workflow must exist"
        return PACKER_WORKFLOW.read_text()

    def test_cleanup_step_runs_always(self, workflow_content):
        """Orphaned builders must be terminated even when the build step fails."""
        cleanup_body = self._cleanup_step_body(workflow_content)
        assert "if: always()" in cleanup_body

    def test_cleanup_selects_builder_run_tag(self, workflow_content):
        """Cleanup must filter on the controlled packer-builder-<ami_type> tag and terminate."""
        cleanup_body = self._cleanup_step_body(workflow_content)
        assert "packer-builder-${{ inputs.ami_type }}" in cleanup_body
        assert "terminate-instances" in cleanup_body

    def test_ssm_update_precedes_cleanup(self, workflow_content):
        """SSM publication stays success-only; cleanup is defense-in-depth after it."""
        ssm_idx = workflow_content.index("- name: Update")
        cleanup_idx = workflow_content.index(self.CLEANUP_STEP_NAME)
        assert ssm_idx < cleanup_idx
