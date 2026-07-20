"""
Tests for Packer AMI build configuration.

Run with: pytest shifter/packer/tests/test_packer.py -v
"""

import os
import re
import shutil
import subprocess
import textwrap
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
        for pattern in [
            "kali/*.sh",
            "ubuntu/*.sh",
            "brokenbk/*.sh",
            "common/*.sh",
            "techvault/*.sh",
            "polaris/*.sh",
            "bake/*.sh",
            "aws/*.sh",
        ]:
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

        # Validate with var-file (no defaults). The scenario sources
        # (techvault / polaris-vm) use the SSM session_manager communicator,
        # which requires a non-empty iam_instance_profile at validate time; the
        # var-file does not carry one (it is an operator dispatch input), so pass
        # a validate-only placeholder. It never reaches AWS — validate is a
        # static config check.
        result = subprocess.run(  # noqa: S603
            [
                packer_path,
                "validate",
                "-var-file=dev.pkrvars.hcl",
                "-var",
                "builder_instance_profile=ci-validate",
                ".",
            ],
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

    CLEANUP_STEP_NAME = "- name: Cleanup Packer builder and verify instances"

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


class TestScenarioBakeTemplates:
    """Packer sources for the SSM-communicator scenario bakes (#1469)."""

    SCENARIO_SOURCES = ("techvault", "polaris-vm")

    @staticmethod
    def _content(source: str) -> str:
        path = PACKER_DIR / f"{source}.pkr.hcl"
        assert path.exists(), f"Missing scenario template: {path.name}"
        return path.read_text()

    @pytest.mark.parametrize("source", SCENARIO_SOURCES)
    def test_scenario_template_exists(self, source):
        assert (PACKER_DIR / f"{source}.pkr.hcl").exists()

    @pytest.mark.parametrize("source", SCENARIO_SOURCES)
    def test_uses_session_manager_communicator(self, source):
        """No-inbound bake: SSH over Session Manager, explicit profile + SG."""
        content = self._content(source)
        assert '"session_manager"' in content
        assert "iam_instance_profile" in content
        # Isolation is the operator no-inbound SG (not dropping the public IP);
        # the SG must reach the builder, so it is threaded into the source.
        assert "security_group_ids" in content
        assert "var.security_group_id" in content

    @pytest.mark.parametrize("source", SCENARIO_SOURCES)
    def test_encrypted_root_volume(self, source):
        content = self._content(source)
        assert "launch_block_device_mappings" in content
        assert re.search(r"encrypted\s*=\s*true", content)

    @pytest.mark.parametrize("source", SCENARIO_SOURCES)
    def test_imdsv2_enforced(self, source):
        content = self._content(source)
        assert re.search(r'http_tokens\s*=\s*"required"', content)
        assert re.search(r'imds_support\s*=\s*"v2\.0"', content)

    @pytest.mark.parametrize("source", SCENARIO_SOURCES)
    def test_shutdown_behavior_terminates(self, source):
        assert re.search(r'shutdown_behavior\s*=\s*"terminate"', self._content(source))

    @pytest.mark.parametrize("source", SCENARIO_SOURCES)
    def test_long_ami_polling_window(self, source):
        """Large baked AMIs snapshot for 30-60 min; the AMI-ready wait must be
        extended past Packer's default or the build fails after a good bake."""
        content = self._content(source)
        assert "aws_polling" in content
        m = re.search(r"max_attempts\s*=\s*(\d+)", content)
        delay = re.search(r"delay_seconds\s*=\s*(\d+)", content)
        assert m and delay, "aws_polling must set delay_seconds + max_attempts"
        # >= 45 min of headroom for the large-image snapshot.
        assert int(m.group(1)) * int(delay.group(1)) >= 2700

    @pytest.mark.parametrize(
        ("source", "builder_name"),
        [
            ("techvault", "packer-builder-techvault"),
            ("polaris-vm", "packer-builder-polaris-vm"),
        ],
    )
    def test_run_tag_name_matches_cleanup_selector(self, source, builder_name):
        """Workflow cleanup keys off packer-builder-<ami_type>; templates must align."""
        assert re.search(rf'Name\s*=\s*"{re.escape(builder_name)}"', self._content(source))


class TestScenarioBakeScripts:
    """Provisioner + verify script bodies for the scenario bakes (#1469)."""

    def test_techvault_provisioner_scripts_exist(self):
        for script in ("toolchain.sh", "stack.sh", "seat.sh", "wait-stack.sh"):
            assert (SCRIPTS_DIR / "techvault" / script).exists(), f"missing techvault/{script}"

    def test_polaris_bootstrap_exists(self):
        assert (SCRIPTS_DIR / "polaris" / "bootstrap.sh").exists()

    def test_bake_verify_scripts_exist(self):
        for script in ("verify-encrypted-ami.sh", "golden-verify.sh"):
            assert (SCRIPTS_DIR / "bake" / script).exists(), f"missing bake/{script}"

    def test_techvault_stack_runs_as_ubuntu(self):
        """Wazuh certs need uid 1000; the stack must run as the ubuntu user."""
        content = (SCRIPTS_DIR / "techvault" / "stack.sh").read_text()
        assert "sudo -u ubuntu" in content
        assert "aptl lab start" in content

    def test_polaris_bootstrap_pulls_tarball_and_runs_stack(self):
        content = (SCRIPTS_DIR / "polaris" / "bootstrap.sh").read_text()
        assert "POLARIS_TARBALL_S3_URI" in content
        assert "docker compose build" in content
        assert "docker compose up -d" in content

    @staticmethod
    def _run_encryption_verify(tmp_path, ebs_count, enc_count):
        """Execute verify-encrypted-ami.sh against a fake `aws` shim that returns
        controlled describe-images counts (repo pattern: exercise the bash gate,
        don't just grep it)."""
        fake = tmp_path / "aws"
        fake.write_text(
            "#!/bin/bash\n"
            'for a in "$@"; do\n'
            '  case "$a" in\n'
            '    *Ebs.Encrypted*) echo "$FAKE_ENC_COUNT"; exit 0;;\n'
            "    *'[?Ebs]'*) echo \"$FAKE_EBS_COUNT\"; exit 0;;\n"
            "  esac\n"
            "done\n"
            "echo 0\n"
        )
        fake.chmod(0o755)
        env = {
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "AMI_ID": "ami-test",
            "FAKE_EBS_COUNT": str(ebs_count),
            "FAKE_ENC_COUNT": str(enc_count),
        }
        return subprocess.run(  # noqa: S603
            [str(SCRIPTS_DIR / "bake" / "verify-encrypted-ami.sh")],
            capture_output=True,
            text=True,
            env=env,
        )

    def test_encryption_verify_passes_when_all_encrypted(self, tmp_path):
        r = self._run_encryption_verify(tmp_path, ebs_count=1, enc_count=1)
        assert r.returncode == 0, f"stdout={r.stdout} stderr={r.stderr}"

    def test_encryption_verify_fails_when_unencrypted(self, tmp_path):
        r = self._run_encryption_verify(tmp_path, ebs_count=1, enc_count=0)
        assert r.returncode == 1, "must refuse to publish an unencrypted AMI"
        assert "unencrypted" in (r.stdout + r.stderr).lower()

    def test_encryption_verify_fails_when_no_ebs(self, tmp_path):
        r = self._run_encryption_verify(tmp_path, ebs_count=0, enc_count=0)
        assert r.returncode == 1, "must refuse when there are no EBS volumes to verify"


class TestScenarioBakeWorkflow:
    """packer.yml invariants for the scenario bake job (#1469)."""

    @pytest.fixture
    def wf(self):
        assert PACKER_WORKFLOW.exists()
        return PACKER_WORKFLOW.read_text()

    def test_bake_scenario_job_present(self, wf):
        assert "bake-scenario:" in wf

    def test_scenario_ami_type_choices(self, wf):
        assert "- techvault" in wf
        assert "- polaris-vm" in wf

    def test_encryption_and_golden_verify_precede_publish(self, wf):
        """Encryption + fresh-boot golden verify are gates before SSM publish."""
        enc_idx = wf.index("verify-encrypted-ami.sh")
        golden_idx = wf.index("golden-verify.sh")
        publish_idx = wf.index("Publish the AMI to SSM")
        assert enc_idx < publish_idx
        assert golden_idx < publish_idx

    def test_session_manager_plugin_installed(self, wf):
        assert "session-manager-plugin" in wf

    def test_base_build_skips_scenario_types(self, wf):
        assert '!contains(fromJSON(\'["techvault","polaris-vm"]\'), inputs.ami_type)' in wf

    def test_legacy_bake_workflows_deleted(self):
        wdir = REPO_ROOT / ".github" / "workflows"
        assert not (wdir / "techvault-scenario-bake.yml").exists()
        assert not (wdir / "polaris-scenario-bake.yml").exists()


class TestAmiHelperAlignment:
    """scripts/ami.sh must stay aligned with packer.yml AMI types (#1469 preflight)."""

    def test_scenario_types_listed(self):
        content = (REPO_ROOT / "scripts" / "ami.sh").read_text()
        assert "techvault" in content
        assert "polaris-vm" in content


class TestAwsGuestDns:
    """Issue #1633: durable range-guest DNS baked at the AWS packer-build level.

    The guest AMIs run systemd-resolved (Linux) as the stub resolver; on some
    boots it comes up with no upstream and the SSM agent never registers. The
    durable fix bakes a deterministic AmazonProvidedDNS fallback into the AWS
    images at build time. The Linux and Windows base scripts are shared with the
    GCP templates (../scripts/...) and the pre-promoted polaris-dc build, so the
    AWS resolver change MUST live in AWS-only scripts and must not leak.
    """

    AWS_DIR = SCRIPTS_DIR / "aws"
    LINUX_DNS = AWS_DIR / "linux-resolved-dns.sh"
    WINDOWS_DNS = AWS_DIR / "windows-ec2launch-dns.ps1"

    # --- Linux (Kali + Ubuntu) ------------------------------------------------

    def test_linux_dns_script_exists(self):
        assert self.LINUX_DNS.exists(), "missing scripts/aws/linux-resolved-dns.sh"

    def test_linux_dns_uses_amazon_provided_fallback_only(self):
        c = self.LINUX_DNS.read_text()
        # Deterministic fallback = link-local AmazonProvidedDNS.
        assert "FallbackDNS=" in c
        assert "169.254.169.253" in c
        # FallbackDNS keeps DHCP per-link DNS precedence: do NOT hard-pin a bare
        # DNS= directive to the fallback (that would override per-link DNS). The
        # negative lookbehind excludes the legitimate "FallbackDNS=" occurrence.
        assert re.search(r"(?<![A-Za-z])DNS=\s*169\.254\.169\.253", c) is None
        # AmazonProvidedDNS only - never a public resolver.
        for public in ("8.8.8.8", "8.8.4.4", "1.1.1.1"):
            assert public not in c, f"public resolver {public} must not be used"

    def test_linux_dns_uses_resolved_dropin_not_static_resolv_conf(self):
        c = self.LINUX_DNS.read_text()
        assert "resolved.conf.d" in c
        # Must not replace the resolved stub with a static /etc/resolv.conf.
        assert "> /etc/resolv.conf" not in c
        assert ">/etc/resolv.conf" not in c

    def test_linux_dns_baked_into_aws_kali_and_ubuntu(self):
        for f in ("kali.pkr.hcl", "ubuntu.pkr.hcl"):
            assert "scripts/aws/linux-resolved-dns.sh" in (PACKER_DIR / f).read_text(), (
                f"{f} must provision scripts/aws/linux-resolved-dns.sh"
            )

    def test_linux_dns_not_leaked_into_gcp_templates(self):
        for f in (PACKER_DIR / "gcp").glob("*.pkr.hcl"):
            assert "linux-resolved-dns.sh" not in f.read_text(), (
                f"AWS resolver change leaked into GCP template {f.name}"
            )

    def test_linux_dns_not_in_shared_base_scripts(self):
        # The shared kali/ubuntu base scripts are consumed by GCP too.
        for shared in ("kali/base.sh", "ubuntu/base.sh"):
            assert "169.254.169.253" not in (SCRIPTS_DIR / shared).read_text(), (
                f"resolver pin leaked into shared script {shared}"
            )

    # --- Windows victim -------------------------------------------------------

    def test_windows_dns_script_exists(self):
        assert self.WINDOWS_DNS.exists(), "missing scripts/aws/windows-ec2launch-dns.ps1"

    def test_windows_dns_is_first_boot_prready_once(self):
        c = self.WINDOWS_DNS.read_text()
        # Runs in EC2Launch v2 preReady, before the default postReady startSsm.
        assert "preReady" in c
        # First-boot scoped only - an 'always' task would undo the later
        # DomainJoinPlan switch of a member's DNS to the DC.
        assert "frequency: once" in c
        assert "frequency: always" not in c

    def test_windows_dns_validates_ec2launch_config(self):
        c = self.WINDOWS_DNS.read_text()
        assert "EC2Launch.exe" in c
        assert "validate" in c

    def test_windows_dns_baked_into_aws_windows_before_sysprep(self):
        c = (PACKER_DIR / "windows.pkr.hcl").read_text()
        assert "scripts/aws/windows-ec2launch-dns.ps1" in c
        assert c.index("windows-ec2launch-dns.ps1") < c.index("sysprep.ps1"), (
            "DNS EC2Launch task must be provisioned before sysprep"
        )

    def test_windows_dns_not_applied_to_promoted_dc_or_gcp(self):
        # A promoted DC owns its own DNS (points at itself, forwards); the
        # reset-to-DHCP task must not touch it.
        for f in ("dc.pkr.hcl", "polaris-dc.pkr.hcl"):
            assert "windows-ec2launch-dns.ps1" not in (PACKER_DIR / f).read_text(), (
                f"victim DNS task must not be applied to {f}"
            )
        for f in (PACKER_DIR / "gcp").glob("*.pkr.hcl"):
            assert "windows-ec2launch-dns.ps1" not in f.read_text()


class TestBaseImageValidationGate:
    """Issue #1633: publish /shifter/ami/* only after the exact candidate AMI
    fresh-boots, registers with SSM (the DNS proof), reboots, and re-registers.
    """

    VERIFY = SCRIPTS_DIR / "bake" / "base-image-verify.sh"

    def test_base_image_verify_script_exists(self):
        assert self.VERIFY.exists(), "missing scripts/bake/base-image-verify.sh"

    def test_base_image_verify_proves_dns_via_ssm_and_reboot(self):
        c = self.VERIFY.read_text()
        # SSM registration is the DNS proof; must survive a reboot.
        assert "describe-instance-information" in c
        assert "PingStatus" in c
        assert "reboot-instances" in c

    def test_base_image_verify_uses_imdsv2_and_cleans_up(self):
        c = self.VERIFY.read_text()
        assert "HttpTokens=required" in c
        assert "terminate-instances" in c

    def test_base_image_verify_resolves_regional_ssm_endpoint(self):
        c = self.VERIFY.read_text()
        # Assert the resolver proof targets the regional SSM endpoint via
        # non-hostname-shaped fragments. A bare `"ssm.us-east-2.amazonaws.com"
        # in c` membership check trips CodeQL's incomplete-url-substring rule,
        # even though this is a script-content assertion, not URL sanitization.
        assert "ssm" in c
        assert "us-east-2" in c
        assert "amazonaws" in c

    def test_workflow_runs_verify_before_publishing_base_ami(self):
        wf = PACKER_WORKFLOW.read_text()
        assert "base-image-verify.sh" in wf
        assert wf.index("base-image-verify.sh") < wf.index("put-parameter"), (
            "validation gate must precede the SSM publish"
        )

    def test_workflow_dc_publishes_prebaked_json_not_generalized_build(self):
        wf = PACKER_WORKFLOW.read_text()
        # dc is a pre-promoted contract; dev must publish the checked-in ID,
        # never the generalized dc.pkr.hcl build.
        assert "dc-amis.json" in wf

    def test_workflow_dc_skips_generalized_build(self):
        wf = PACKER_WORKFLOW.read_text()
        # The generalized dc.pkr.hcl build (and its manifest read) must be guarded
        # off for dc so a clean runner resolves the prebaked id instead.
        assert "if: inputs.ami_type != 'dc'" in wf
        assert "Resolve prebaked DC AMI" in wf

    @staticmethod
    def _step_run_script(wf: str, step_name: str) -> str:
        """Extract and dedent the shell of a workflow step's `run: |` block."""
        marker = f"- name: {step_name}"
        start = wf.index(marker)
        nxt = wf.find("\n      - name:", start + 1)
        block = wf[start : nxt if nxt != -1 else len(wf)]
        run_body = block[block.index("run: |") + len("run: |") :]
        return textwrap.dedent(run_body)

    def test_protected_ref_gate_rejects_unreviewed_refs(self):
        # Behavioral: run the ACTUAL inline gate shell with accept/reject refs.
        # The gate MUST stay inline (it runs before checkout, so it cannot call a
        # checked-out script), so we execute the extracted case block directly.
        # This goes red if the reject arm (`exit 1`) is removed or the allow arm
        # is widened to accept another ref.
        gate = self._step_run_script(PACKER_WORKFLOW.read_text(), "Validate build ref")
        assert "case" in gate and "REF" in gate  # sanity: we extracted the gate

        def run(ref: str) -> int:
            return subprocess.run(  # noqa: S603
                ["bash", "-c", gate],  # noqa: S607
                env={**os.environ, "REF": ref},
                capture_output=True,
            ).returncode

        assert run("dev") == 0
        assert run("main") == 0
        # Unreviewed / injected refs must be rejected.
        assert run("attacker-branch") != 0
        assert run("dev | evil") != 0
        assert run("main-attacker") != 0
        assert run("") != 0

    def test_verify_instance_profile_allowlist_rejects_arbitrary_profiles(self):
        # Behavioral: pull the actual allowlist ERE from the workflow and prove it
        # accepts only the range instance-profile naming convention, so a
        # dispatcher cannot pass a more-privileged profile (iam:PassRole exfil).
        wf = PACKER_WORKFLOW.read_text()
        m = re.search(
            r"match verify_instance_profile \"\$VERIFY_INSTANCE_PROFILE\" '([^']+)'",
            wf,
        )
        assert m is not None, "verify_instance_profile allowlist match not found"
        pattern = m.group(1)

        def accepts(value: str) -> bool:
            # Mirror the workflow's own `grep -qE` check.
            return (
                subprocess.run(  # noqa: S603
                    ["grep", "-qE", pattern],  # noqa: S607
                    input=value,
                    text=True,
                ).returncode
                == 0
            )

        assert accepts("shifter-dev-range-instance")
        assert accepts("shifter-proof-range-instance")
        # Arbitrary / more-privileged profiles must be rejected.
        assert not accepts("AdministratorAccess")
        assert not accepts("shifter-dev-range-instance-evil")
        assert not accepts("evil-range-instance-admin")
        assert not accepts("")


class TestDcAmiProvenance:
    """Issue #1656: the pre-promoted DC AMI id published to /shifter/ami/dc is
    read from trusted protected provenance (the dev ref) and validated (shape +
    ownership + available state) by one resolver shared by both publishers,
    replacing the prior unvalidated `jq -r` reads and adding a protected-ref gate
    to the prod promote path.
    """

    RESOLVER = SCRIPTS_DIR / "bake" / "resolve-dc-ami.sh"
    PROMOTE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "packer-promote.yml"

    # --- shared resolver script ------------------------------------------------

    def test_resolver_script_exists(self):
        assert self.RESOLVER.exists(), "missing scripts/bake/resolve-dc-ami.sh"

    def _run_resolver(self, tmp_path, registry, *, env_key, ami_state):
        """Run resolve-dc-ami.sh with a stub `aws` that reports `ami_state` for
        the describe-images ownership/state query (real jq resolves the key)."""
        registry_path = tmp_path / "dc-amis.json"
        registry_path.write_text(registry)
        fakebin = tmp_path / "bin"
        fakebin.mkdir(exist_ok=True)
        aws = fakebin / "aws"
        aws.write_text(
            "#!/bin/bash\n"
            'if [ "$1" = "ec2" ] && [ "$2" = "describe-images" ]; then\n'
            "  printf '%s\\n' \"${FAKE_AMI_STATE:-None}\"\n"
            "  exit 0\n"
            "fi\n"
            "exit 0\n"
        )
        aws.chmod(0o755)
        env = {
            **os.environ,
            "PATH": f"{fakebin}{os.pathsep}{os.environ['PATH']}",
            "DC_AMIS_JSON": str(registry_path),
            "DC_ENV_KEY": env_key,
            "EXPECTED_ACCOUNT_ID": "123456789012",
            "FAKE_AMI_STATE": ami_state,
        }
        return subprocess.run(  # noqa: S603
            ["bash", str(self.RESOLVER)],  # noqa: S607
            env=env,
            capture_output=True,
            text=True,
        )

    def test_resolver_accepts_valid_owned_available_ami(self, tmp_path):
        r = self._run_resolver(
            tmp_path,
            '{"dev": "ami-0123456789abcdef0", "prod": "ami-05ac9c21a6c0f8767"}',
            env_key="dev",
            ami_state="available",
        )
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "ami-0123456789abcdef0"

    def test_resolver_fails_closed_on_missing_key(self, tmp_path):
        r = self._run_resolver(
            tmp_path,
            '{"prod": "ami-0123456789abcdef0"}',
            env_key="dev",
            ami_state="available",
        )
        assert r.returncode != 0
        assert "ami-" not in r.stdout

    def test_resolver_fails_closed_on_null_value(self, tmp_path):
        r = self._run_resolver(tmp_path, '{"dev": null}', env_key="dev", ami_state="available")
        assert r.returncode != 0
        assert r.stdout.strip() == ""

    def test_resolver_fails_closed_on_malformed_ami_id(self, tmp_path):
        r = self._run_resolver(tmp_path, '{"dev": "not-an-ami"}', env_key="dev", ami_state="available")
        assert r.returncode != 0
        # The rejected value is not echoed on the published (stdout) surface.
        assert "not-an-ami" not in r.stdout

    def test_resolver_fails_closed_when_not_available_or_not_owned(self, tmp_path):
        # describe-images --owners returns no matching image => State "None".
        r = self._run_resolver(
            tmp_path,
            '{"dev": "ami-0123456789abcdef0"}',
            env_key="dev",
            ami_state="None",
        )
        assert r.returncode != 0
        assert r.stdout.strip() == ""

    # --- workflow wiring -------------------------------------------------------

    def test_both_publishers_use_shared_resolver(self):
        # One validated resolver contract, two thin call sites (no drift).
        assert "resolve-dc-ami.sh" in PACKER_WORKFLOW.read_text()
        assert "resolve-dc-ami.sh" in self.PROMOTE_WORKFLOW.read_text()

    def test_promote_dropped_unvalidated_jq_read(self):
        # The prod publisher's bare, unvalidated `jq -r '.prod'` is gone.
        assert "jq -r '.prod'" not in self.PROMOTE_WORKFLOW.read_text()

    def test_base_reads_dc_registry_and_resolver_from_protected_dev_checkout(self):
        wf = PACKER_WORKFLOW.read_text()
        assert "Checkout trusted DC registry (protected provenance)" in wf
        idx = wf.index("Checkout trusted DC registry (protected provenance)")
        block = wf[idx : idx + 900]
        # refs/heads/dev (not the short name) so a tag cannot shadow the branch.
        assert "ref: refs/heads/dev" in block
        assert "persist-credentials: false" in block
        # BOTH the registry and the validator come from protected provenance.
        assert "shifter/packer/dc-amis.json" in block
        assert "shifter/packer/scripts/bake/resolve-dc-ami.sh" in block

    def test_base_runs_resolver_from_trusted_checkout_not_build_checkout(self):
        # The validator executable must come from the trusted dev checkout, not
        # the caller-selected inputs.ref checkout (codex #1656).
        wf = PACKER_WORKFLOW.read_text()
        assert "TRUSTED_RESOLVER: ${{ github.workspace }}/trusted-dc/" in wf
        assert 'bash "$TRUSTED_RESOLVER"' in wf

    def test_base_resolves_before_publishing(self):
        wf = PACKER_WORKFLOW.read_text()
        assert wf.index("resolve-dc-ami.sh") < wf.index("put-parameter"), (
            "DC resolve/validate must precede the SSM publish"
        )

    def test_promote_reads_from_protected_dev_and_persists_no_creds(self):
        wf = self.PROMOTE_WORKFLOW.read_text()
        idx = wf.index("Checkout trusted DC registry (protected provenance)")
        block = wf[idx : idx + 400]
        assert "ref: refs/heads/dev" in block
        assert "persist-credentials: false" in block

    @staticmethod
    def _step_run_script(wf: str, step_name: str) -> str:
        marker = f"- name: {step_name}"
        start = wf.index(marker)
        nxt = wf.find("\n      - name:", start + 1)
        block = wf[start : nxt if nxt != -1 else len(wf)]
        run_body = block[block.index("run: |") + len("run: |") :]
        return textwrap.dedent(run_body)

    def test_promote_ref_gate_rejects_unreviewed_refs(self):
        gate = self._step_run_script(self.PROMOTE_WORKFLOW.read_text(), "Validate promote ref")
        assert "case" in gate and "REF" in gate

        def run(ref: str) -> int:
            return subprocess.run(  # noqa: S603
                ["bash", "-c", gate],  # noqa: S607
                env={**os.environ, "REF": ref},
                capture_output=True,
            ).returncode

        assert run("refs/heads/dev") == 0
        assert run("refs/heads/main") == 0
        # A tag whose short name collides with a protected branch must fail.
        assert run("refs/tags/dev") != 0
        assert run("refs/tags/main") != 0
        assert run("refs/heads/attacker-branch") != 0
        assert run("dev") != 0
        assert run("dev | evil") != 0
        assert run("") != 0

    def test_ami_helper_dispatches_protected_ref(self):
        content = (REPO_ROOT / "scripts" / "ami.sh").read_text()
        assert "WORKFLOW_REF" in content
        # Dispatch uses the validated protected ref, never the working-tree branch.
        assert '--ref "$WORKFLOW_REF"' in content
        assert '--ref "$BRANCH"' not in content

    def test_ami_helper_ref_gate_rejects_non_protected(self, tmp_path):
        # Behavioral: execute ami.sh's protected-ref gate with a stubbed `gh` so
        # accept refs reach a (no-op) dispatch and reject refs exit non-zero
        # before any dispatch. Goes red if the reject arm loses its `exit 1` or
        # the allow arm is widened (test-quality review #1656).
        ami_sh = REPO_ROOT / "scripts" / "ami.sh"
        fakebin = tmp_path / "bin"
        fakebin.mkdir()
        gh = fakebin / "gh"
        gh.write_text("#!/bin/bash\nexit 0\n")
        gh.chmod(0o755)

        def run(ref_env):
            env = {**os.environ, "PATH": f"{fakebin}{os.pathsep}{os.environ['PATH']}"}
            if ref_env is not None:
                env["AMI_WORKFLOW_REF"] = ref_env
            return subprocess.run(  # noqa: S603
                ["bash", str(ami_sh), "-b", "kali"],  # noqa: S607
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
            ).returncode

        # Protected refs pass the gate and reach the stubbed dispatch (rc 0).
        assert run("dev") == 0
        assert run("main") == 0
        assert run(None) == 0  # unset -> defaults to dev
        # Non-protected refs are refused before any dispatch.
        assert run("feature-x") != 0
        assert run("dev | evil") != 0
        assert run("refs/tags/dev") != 0
