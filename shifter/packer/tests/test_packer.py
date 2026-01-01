"""
Tests for Packer AMI build configuration.

Run with: pytest shifter/packer/tests/test_packer.py -v
"""

import os
import subprocess
from pathlib import Path

import pytest

PACKER_DIR = Path(__file__).parent.parent
SCRIPTS_DIR = PACKER_DIR / "scripts"


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

    def test_cleanup_script_exists(self):
        """Cleanup script should exist."""
        assert (SCRIPTS_DIR / "common" / "cleanup.sh").exists()


class TestScriptContent:
    """Test script content for best practices."""

    @pytest.fixture
    def all_scripts(self):
        scripts = []
        for pattern in ["kali/*.sh", "ubuntu/*.sh", "common/*.sh"]:
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
                        if pattern.lower() in line
                        and "=$" not in line
                        and '=""' not in line
                    ]
                    assert not any(
                        "=" in line and not line.strip().startswith("#")
                        for line in lines
                    ), f"{script.name} may contain hardcoded secret: {pattern}"

    def test_noninteractive_apt(self, all_scripts):
        """Scripts using apt should be non-interactive."""
        for script in all_scripts:
            content = script.read_text()
            if "apt-get install" in content:
                has_noninteractive = (
                    "DEBIAN_FRONTEND=noninteractive" in content
                    or "apt-get install -y" in content
                )
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

    def test_variables_file_exists(self):
        """Variables file should exist."""
        assert (PACKER_DIR / "variables.pkr.hcl").exists()

    @pytest.mark.skipif(
        subprocess.run(["which", "packer"], capture_output=True).returncode != 0,
        reason="Packer not installed",
    )
    def test_packer_validate(self):
        """Packer templates should be valid."""
        os.chdir(PACKER_DIR)

        # Init first
        subprocess.run(["packer", "init", "."], capture_output=True)

        # Validate with var-file (no defaults)
        result = subprocess.run(
            ["packer", "validate", "-var-file=dev.pkrvars.hcl", "."],
            capture_output=True,
            text=True,
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
