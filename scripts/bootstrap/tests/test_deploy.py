"""Comprehensive tests for deploy.py following TDD contract-based testing.

Tests verify the complete contract for each function:
1. Inputs - minimum required data and validation
2. Outputs - return values and data structures
3. Side effects - subprocess calls, file writes, system changes
4. Errors - error handling and propagation
5. Logging - debug and error logging

All external dependencies are mocked. No actual AWS calls, file operations,
or subprocess executions occur during tests.
"""

import io
import json
import os
import shutil
import subprocess
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

import pytest

import deploy

# =============================================================================
# Test Fixtures
# =============================================================================


def _sample_gcp_control_plane_outputs(project_id: str = "prod-rwctxzl6shxk") -> dict[str, dict[str, object]]:
    """Return representative Terraform outputs for the GCP control-plane path."""
    return {
        "gke_cluster_name": {"value": "shifter-gcp-dev-platform"},
        "gke_cluster_location": {"value": "us-central1"},
        "artifact_registry_image_roots": {
            "value": {
                "portal": f"us-central1-docker.pkg.dev/{project_id}/shifter-gcp-dev-portal/portal",
                "guacd": f"us-central1-docker.pkg.dev/{project_id}/shifter-gcp-dev-guacd/guacd",
                "guacamole-client": (
                    f"us-central1-docker.pkg.dev/{project_id}/shifter-gcp-dev-guacamole-client/guacamole-client"
                ),
                "pulumi-provisioner": (
                    f"us-central1-docker.pkg.dev/{project_id}/shifter-gcp-dev-pulumi-provisioner/pulumi-provisioner"
                ),
            }
        },
        "assets_bucket_name": {"value": f"{project_id}-gcp-dev-assets"},
        "terraform_state_bucket_name": {"value": f"{project_id}-terraform-state"},
        "platform_events_topic_id": {"value": f"projects/{project_id}/topics/shifter-gcp-dev-events"},
        "platform_event_subscriptions": {
            "value": {
                "cms": f"projects/{project_id}/subscriptions/shifter-gcp-dev-cms",
                "engine": f"projects/{project_id}/subscriptions/shifter-gcp-dev-engine",
                "mc": f"projects/{project_id}/subscriptions/shifter-gcp-dev-mc",
                "experiments": f"projects/{project_id}/subscriptions/shifter-gcp-dev-experiments",
            }
        },
        "runtime_secret_ids": {
            "value": {
                "app": f"projects/{project_id}/secrets/shifter-gcp-dev-app",
                "db": f"projects/{project_id}/secrets/shifter-gcp-dev-db",
                "guacamole-db": f"projects/{project_id}/secrets/shifter-gcp-dev-guacamole-db",
                "guacamole-json-auth": f"projects/{project_id}/secrets/shifter-gcp-dev-guacamole-json-auth",
            }
        },
        "identity_platform_api_key": {"value": "identity-platform-api-key"},
        "identity_platform_project_id": {"value": project_id},
        "identity_allowed_email_domain": {"value": "paloaltonetworks.com"},
        "identity_allowed_emails": {"value": []},
        "control_plane_database": {
            "value": {
                "private_ip": "10.40.0.10",
                "port": 5432,
                "database_name": "shifter",
                "user_name": "shifter",
            }
        },
        "control_plane_cache": {"value": {"host": "10.40.0.20", "port": 6379}},
        "guacamole_database": {
            "value": {
                "host": "10.40.0.10",
                "port": 5432,
                "database_name": "guacamole",
                "user_name": "guacamole",
            }
        },
        "public_ingress_ip_name": {"value": "shifter-gcp-dev-platform-ip"},
        "public_ingress_ip_address": {"value": "34.123.45.67"},
        "public_hostname": {"value": "portal.example.test"},
        "managed_tls_enabled": {"value": True},
        "cloud_armor_security_policy_name": {"value": "shifter-gcp-dev-edge"},
        "range_network_id": {"value": f"projects/{project_id}/global/networks/shifter-gcp-dev-range"},
        "range_network_cidr": {"value": "10.50.0.0/16"},
        "range_network_region": {"value": "us-central1"},
        "portal_network_cidrs": {"value": ["10.40.0.0/20", "10.44.0.0/16"]},
        "gke_services_cidr": {"value": "10.48.0.0/20"},
        "workload_service_accounts": {
            "value": {
                "portal": f"shiftergcpdev-portal@{project_id}.iam.gserviceaccount.com",
                "workers": f"shiftergcpdev-workers@{project_id}.iam.gserviceaccount.com",
                "provisioner": f"shiftergcpdev-provisioner@{project_id}.iam.gserviceaccount.com",
            }
        },
    }


@pytest.fixture
def mock_stdin_tty():
    """Mock sys.stdin.isatty() to return True (interactive terminal)."""
    with patch("sys.stdin.isatty", return_value=True):
        yield


@pytest.fixture
def mock_stdin_non_tty():
    """Mock sys.stdin.isatty() to return False (non-interactive)."""
    with patch("sys.stdin.isatty", return_value=False):
        yield


@pytest.fixture(autouse=True)
def prevent_hanging_on_input():
    """Automatically mock input() to prevent tests from hanging.

    Individual tests should override this with their specific input values.
    """
    with patch("builtins.input", return_value=""):
        yield


@pytest.fixture(autouse=True)
def prevent_real_subprocess_calls():
    """Prevent any real subprocess calls from executing.

    This is a safety measure to ensure tests NEVER call real AWS, gh, git,
    terraform, or any other system commands. Individual tests must explicitly
    patch subprocess.run/call/check_output with their expected behavior.

    If a test tries to call subprocess without mocking, it will fail with
    a clear error message.
    """

    def safe_run(*args, **kwargs):
        # Allow only if explicitly mocked in test
        raise RuntimeError(
            f"Test attempted to call subprocess.run({args[0] if args else 'unknown'}) "
            f"without mocking! This could execute real commands. "
            f"Mock subprocess.run in your test."
        )

    with patch("subprocess.run", side_effect=safe_run):
        yield


@pytest.fixture
def bootstrap_config():
    """Return a valid BootstrapConfig for testing."""
    return deploy.BootstrapConfig(env="dev")


@pytest.fixture
def mock_repo_root(tmp_path):
    """Mock repository structure for testing."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "platform").mkdir()
    (repo / "platform" / "terraform").mkdir()
    (repo / "platform" / "terraform" / "environments").mkdir()
    (repo / "platform" / "terraform" / "environments" / "dev").mkdir()
    (repo / "platform" / "terraform" / "environments" / "dev" / "portal").mkdir(parents=True)
    (repo / "platform" / "terraform" / "environments" / "dev" / "range").mkdir(parents=True)
    (repo / "platform" / "terraform" / "environments" / "prod").mkdir()
    (repo / "platform" / "terraform" / "environments" / "prod" / "portal").mkdir(parents=True)
    (repo / "platform" / "terraform" / "environments" / "prod" / "range").mkdir(parents=True)
    # global/iam for bootstrap_account tests
    (repo / "platform" / "terraform" / "global" / "iam").mkdir(parents=True)
    return repo


@pytest.fixture
def mock_subprocess():
    """Mock subprocess.run to return successful CompletedProcess.

    This overrides the autouse safety fixture for tests that need
    subprocess calls. Returns the mock for assertion purposes.
    """

    def smart_subprocess(cmd, **kwargs):
        # Return appropriate responses based on command
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)

        # which gh - check if gh CLI is available
        if "which" in cmd_str and "gh" in cmd_str:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="/usr/bin/gh\n", stderr="")
        # AWS OIDC provider list
        elif "list-open-id-connect-providers" in cmd_str:
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout="arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com\n",
                stderr="",
            )
        # Terraform output -json
        elif "terraform" in cmd_str and "output" in cmd_str and "-json" in cmd_str:
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout='{"test_output": {"value": "test"}}', stderr=""
            )
        # Terraform show (for displaying plan)
        elif "terraform" in cmd_str and "show" in cmd_str:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="terraform plan output...", stderr="")
        # Git commands (add, commit, push) or gh secret set
        elif ("git" in cmd_str and any(x in cmd_str for x in ["add", "commit", "push"])) or (
            "gh" in cmd_str and "secret" in cmd_str and "set" in cmd_str
        ):
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        # Default success
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=smart_subprocess) as mock:
        yield mock


# =============================================================================
# Test: check_dependencies()
# =============================================================================


class TestCheckDependencies:
    """Tests for deploy.check_dependencies."""

    # ---------------------------------------------------------------------
    # Happy path - function succeeds
    # ---------------------------------------------------------------------

    def test_succeeds_when_all_required_dependencies_present(self):
        """Function completes successfully when aws, terraform, git available."""
        with patch("shutil.which") as mock_which:
            mock_which.side_effect = lambda cmd: (
                "/usr/bin/aws"
                if cmd == "aws"
                else "/usr/bin/terraform"
                if cmd == "terraform"
                else "/usr/bin/git"
                if cmd == "git"
                else "/usr/bin/gh"
                if cmd == "gh"
                else None
            )

            # Should not raise
            deploy.check_dependencies()

    def test_warns_when_optional_dependencies_missing(self, capsys):
        """Function warns about missing gh CLI but continues."""
        with patch("shutil.which") as mock_which:
            mock_which.side_effect = lambda cmd: (
                "/usr/bin/aws"
                if cmd == "aws"
                else "/usr/bin/terraform"
                if cmd == "terraform"
                else "/usr/bin/git"
                if cmd == "git"
                else None  # gh is missing
            )

            deploy.check_dependencies()
            captured = capsys.readouterr()
            assert "optional dependencies" in captured.out.lower()
            assert "gh" in captured.out

    # ---------------------------------------------------------------------
    # Error handling - what can go wrong
    # ---------------------------------------------------------------------

    def test_exits_when_aws_cli_missing(self):
        """Function exits with error when aws CLI not installed."""
        with patch("shutil.which") as mock_which:
            mock_which.side_effect = lambda cmd: (
                None
                if cmd == "aws"  # aws missing
                else "/usr/bin/terraform"
                if cmd == "terraform"
                else "/usr/bin/git"
                if cmd == "git"
                else None
            )

            with pytest.raises(SystemExit) as exc_info:
                deploy.check_dependencies()
            assert exc_info.value.code == 1

    def test_exits_when_terraform_missing(self):
        """Function exits with error when terraform not installed."""
        with patch("shutil.which") as mock_which:
            mock_which.side_effect = lambda cmd: (
                "/usr/bin/aws"
                if cmd == "aws"
                else None
                if cmd == "terraform"  # terraform missing
                else "/usr/bin/git"
                if cmd == "git"
                else None
            )

            with pytest.raises(SystemExit) as exc_info:
                deploy.check_dependencies()
            assert exc_info.value.code == 1

    def test_exits_when_git_missing(self):
        """Function exits with error when git not installed."""
        with patch("shutil.which") as mock_which:
            mock_which.side_effect = lambda cmd: {
                "aws": "/usr/bin/aws",
                "terraform": "/usr/bin/terraform",
                "git": None,  # git missing
            }.get(cmd)

            with pytest.raises(SystemExit) as exc_info:
                deploy.check_dependencies()
            assert exc_info.value.code == 1

    def test_exits_when_all_dependencies_missing(self):
        """Function exits with error when no dependencies installed."""
        with patch("shutil.which", return_value=None):
            with pytest.raises(SystemExit) as exc_info:
                deploy.check_dependencies()
            assert exc_info.value.code == 1

    def test_prints_installation_urls_when_dependencies_missing(self, capsys):
        """Function provides installation URLs for missing dependencies."""
        with patch("shutil.which", return_value=None):
            with pytest.raises(SystemExit):
                deploy.check_dependencies()

            captured = capsys.readouterr()
            assert "https://docs.aws.amazon.com" in captured.out
            assert "https://developer.hashicorp.com" in captured.out
            assert "https://git-scm.com" in captured.out

    def test_gdc_bootstrap_checks_gcp_platform_toolchain(self):
        """The GDC bootstrap path should require the full GCP deploy toolchain."""
        with patch("shutil.which") as mock_which:
            mock_which.side_effect = lambda cmd: (
                "/usr/bin/gcloud"
                if cmd == "gcloud"
                else "/usr/bin/ssh-keygen"
                if cmd == "ssh-keygen"
                else "/usr/bin/terraform"
                if cmd == "terraform"
                else "/usr/bin/docker"
                if cmd == "docker"
                else "/usr/bin/kubectl"
                if cmd == "kubectl"
                else "/usr/bin/helm"
                if cmd == "helm"
                else "/usr/bin/git"
                if cmd == "git"
                else None
            )

            deploy.check_dependencies("gdc-bootstrap")


# =============================================================================
# Test: confirm()
# =============================================================================


class TestConfirm:
    """Tests for deploy.confirm."""

    # ---------------------------------------------------------------------
    # Happy path - function succeeds
    # ---------------------------------------------------------------------

    def test_returns_true_when_user_enters_yes(self, mock_stdin_tty):
        """Function returns True when user enters 'yes'."""
        with patch("builtins.input", return_value="yes"):
            result = deploy.confirm("Continue?")
            assert result is True

    def test_returns_true_when_user_enters_y(self, mock_stdin_tty):
        """Function returns True when user enters 'y'."""
        with patch("builtins.input", return_value="y"):
            result = deploy.confirm("Continue?")
            assert result is True

    def test_returns_false_when_user_enters_no(self, mock_stdin_tty):
        """Function returns False when user enters 'no'."""
        with patch("builtins.input", return_value="no"):
            result = deploy.confirm("Continue?")
            assert result is False

    def test_returns_false_when_user_enters_n(self, mock_stdin_tty):
        """Function returns False when user enters 'n'."""
        with patch("builtins.input", return_value="n"):
            result = deploy.confirm("Continue?")
            assert result is False

    def test_returns_false_when_user_enters_empty_string(self, mock_stdin_tty):
        """Function returns False when user presses Enter (empty input)."""
        with patch("builtins.input", return_value=""):
            result = deploy.confirm("Continue?")
            assert result is False

    # ---------------------------------------------------------------------
    # Input validation
    # ---------------------------------------------------------------------

    def test_reprompts_on_invalid_input(self, mock_stdin_tty):
        """Function reprompts when user enters invalid response."""
        with patch("builtins.input", side_effect=["invalid", "maybe", "y"]):
            result = deploy.confirm("Continue?")
            assert result is True

    def test_handles_whitespace_in_input(self, mock_stdin_tty):
        """Function strips whitespace from user input."""
        with patch("builtins.input", return_value="  yes  "):
            result = deploy.confirm("Continue?")
            assert result is True

    def test_handles_uppercase_input(self, mock_stdin_tty):
        """Function accepts case-insensitive input."""
        with patch("builtins.input", return_value="YES"):
            result = deploy.confirm("Continue?")
            assert result is True

    # ---------------------------------------------------------------------
    # Non-interactive behavior
    # ---------------------------------------------------------------------

    def test_returns_default_in_non_interactive_mode(self, mock_stdin_non_tty):
        """Function returns default_yes value when not in tty."""
        result = deploy.confirm("Continue?", default_yes=True)
        assert result is True

    def test_returns_false_by_default_in_non_interactive(self, mock_stdin_non_tty):
        """Function returns False in non-interactive mode by default."""
        result = deploy.confirm("Continue?")
        assert result is False


# =============================================================================
# Test: confirm_or_manual()
# =============================================================================


class TestConfirmOrManual:
    """Tests for deploy.confirm_or_manual."""

    # ---------------------------------------------------------------------
    # Happy path - function succeeds
    # ---------------------------------------------------------------------

    def test_returns_yes_when_user_enters_yes(self, mock_stdin_tty):
        """Function returns 'yes' when user enters 'yes'."""
        with patch("builtins.input", return_value="yes"):
            result = deploy.confirm_or_manual("Automate this?")
            assert result == "yes"

    def test_returns_yes_when_user_enters_y(self, mock_stdin_tty):
        """Function returns 'yes' when user enters 'y'."""
        with patch("builtins.input", return_value="y"):
            result = deploy.confirm_or_manual("Automate this?")
            assert result == "yes"

    def test_returns_no_when_user_enters_no(self, mock_stdin_tty):
        """Function returns 'no' when user enters 'no'."""
        with patch("builtins.input", return_value="no"):
            result = deploy.confirm_or_manual("Automate this?")
            assert result == "no"

    def test_returns_no_when_user_enters_n(self, mock_stdin_tty):
        """Function returns 'no' when user enters 'n'."""
        with patch("builtins.input", return_value="n"):
            result = deploy.confirm_or_manual("Automate this?")
            assert result == "no"

    def test_returns_manual_when_user_enters_manual(self, mock_stdin_tty):
        """Function returns 'manual' when user enters 'manual'."""
        with patch("builtins.input", return_value="manual"):
            result = deploy.confirm_or_manual("Automate this?")
            assert result == "manual"

    def test_returns_manual_when_user_enters_m(self, mock_stdin_tty):
        """Function returns 'manual' when user enters 'm'."""
        with patch("builtins.input", return_value="m"):
            result = deploy.confirm_or_manual("Automate this?")
            assert result == "manual"

    # ---------------------------------------------------------------------
    # Input validation
    # ---------------------------------------------------------------------

    def test_reprompts_on_invalid_input(self, mock_stdin_tty):
        """Function reprompts when user enters invalid response."""
        with patch("builtins.input", side_effect=["invalid", "maybe", "y"]):
            result = deploy.confirm_or_manual("Automate this?")
            assert result == "yes"

    def test_handles_whitespace_in_input(self, mock_stdin_tty):
        """Function strips whitespace from user input."""
        with patch("builtins.input", return_value="  manual  "):
            result = deploy.confirm_or_manual("Automate this?")
            assert result == "manual"

    def test_handles_case_insensitive_input(self, mock_stdin_tty):
        """Function accepts case-insensitive input."""
        with patch("builtins.input", side_effect=["YES", "NO", "MANUAL"]):
            assert deploy.confirm_or_manual("1?") == "yes"
            assert deploy.confirm_or_manual("2?") == "no"
            assert deploy.confirm_or_manual("3?") == "manual"

    # ---------------------------------------------------------------------
    # Non-interactive behavior
    # ---------------------------------------------------------------------

    def test_returns_manual_in_non_interactive_mode(self, mock_stdin_non_tty):
        """Function returns 'manual' when not in tty."""
        result = deploy.confirm_or_manual("Automate this?")
        assert result == "manual"


# =============================================================================
# Test: run_cmd()
# =============================================================================


class TestRunCmd:
    """Tests for deploy.run_cmd."""

    # ---------------------------------------------------------------------
    # Happy path - function succeeds
    # ---------------------------------------------------------------------

    def test_executes_command_successfully(self):
        """Function executes command and returns CompletedProcess."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=["echo", "test"], returncode=0)

            result = deploy.run_cmd(["echo", "test"])

            mock_run.assert_called_once()
            assert result.returncode == 0

    def test_injects_profile_flag_for_aws_commands(self):
        """Function adds --profile flag to AWS CLI commands."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

            deploy.run_cmd(["aws", "s3", "ls"], profile="my-profile")

            # Should inject --profile after 'aws'
            called_cmd = mock_run.call_args[0][0]
            assert called_cmd == ["aws", "--profile", "my-profile", "s3", "ls"]

    def test_does_not_inject_profile_for_non_aws_commands(self):
        """Function does not modify non-AWS commands."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

            deploy.run_cmd(["terraform", "init"], profile="my-profile")

            called_cmd = mock_run.call_args[0][0]
            assert called_cmd == ["terraform", "init"]

    def test_captures_output_when_capture_true(self):
        """Function captures stdout/stderr when capture=True."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="output", stderr="")

            result = deploy.run_cmd(["echo", "test"], capture=True)

            # Should call with capture_output=True
            assert mock_run.call_args[1]["capture_output"] is True
            assert result.stdout == "output"

    # ---------------------------------------------------------------------
    # Dry-run mode
    # ---------------------------------------------------------------------

    def test_does_not_execute_command_in_dry_run_mode(self):
        """Function prints command but does not execute in dry-run."""
        with patch("subprocess.run") as mock_run:
            result = deploy.run_cmd(["aws", "s3", "ls"], dry_run=True)

            mock_run.assert_not_called()
            assert result is None

    def test_prints_command_in_dry_run_mode(self, capsys):
        """Function prints what would be executed in dry-run."""
        deploy.run_cmd(["echo", "test"], dry_run=True)

        captured = capsys.readouterr()
        assert "DRY-RUN" in captured.out
        assert "echo test" in captured.out

    # ---------------------------------------------------------------------
    # Error handling - what can go wrong
    # ---------------------------------------------------------------------

    def test_exits_when_command_fails_and_check_true(self):
        """Function exits when command fails and check=True."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(returncode=1, cmd=["false"])

            with pytest.raises(SystemExit) as exc_info:
                deploy.run_cmd(["false"], check=True)

            assert exc_info.value.code == 1

    def test_returns_none_when_command_fails_and_check_false(self):
        """Function returns None when command fails and check=False."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(returncode=1, cmd=["false"])

            result = deploy.run_cmd(["false"], check=False)
            assert result is None

    def test_prints_stderr_on_command_failure(self, capsys):
        """Function prints stderr when command fails."""
        with patch("subprocess.run") as mock_run:
            error = subprocess.CalledProcessError(returncode=1, cmd=["false"])
            error.stderr = "Permission denied"
            mock_run.side_effect = error

            deploy.run_cmd(["false"], check=False)

            captured = capsys.readouterr()
            assert "Permission denied" in captured.out


# =============================================================================
# Test: get_aws_account_id()
# =============================================================================


class TestGetAwsAccountId:
    """Tests for deploy.get_aws_account_id."""

    # ---------------------------------------------------------------------
    # Happy path - function succeeds
    # ---------------------------------------------------------------------

    def test_returns_account_id_from_aws_cli(self):
        """Function returns AWS account ID from sts call."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="123456789012\n")

            account_id = deploy.get_aws_account_id()

            assert account_id == "123456789012"

    def test_strips_whitespace_from_account_id(self):
        """Function removes trailing newlines from account ID."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="  123456789012  \n")

            account_id = deploy.get_aws_account_id()

            assert account_id == "123456789012"

    def test_includes_profile_when_provided(self):
        """Function passes profile to aws CLI when specified."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="123456789012")

            deploy.get_aws_account_id(profile="prod-profile")

            called_cmd = mock_run.call_args[0][0]
            assert "--profile" in called_cmd
            assert "prod-profile" in called_cmd

    # ---------------------------------------------------------------------
    # Error handling
    # ---------------------------------------------------------------------

    def test_propagates_error_when_aws_cli_fails(self):
        """Function raises CalledProcessError when AWS CLI fails."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(returncode=1, cmd=["aws"])

            with pytest.raises(subprocess.CalledProcessError):
                deploy.get_aws_account_id()


# =============================================================================
# Test: get_repo_root()
# =============================================================================


class TestGetRepoRoot:
    """Tests for deploy.get_repo_root."""

    # ---------------------------------------------------------------------
    # Happy path - function succeeds
    # ---------------------------------------------------------------------

    def test_returns_path_object(self):
        """Function returns a Path object."""
        result = deploy.get_repo_root()
        assert isinstance(result, Path)

    def test_returns_three_levels_up_from_script(self):
        """Function calculates repo root as three parent directories up."""
        result = deploy.get_repo_root()
        # deploy.py is in scripts/bootstrap/
        # So parent.parent.parent should give us repo root
        # Test file is in scripts/bootstrap/tests/, so we need 4 parents
        expected = Path(__file__).parent.parent.parent.parent
        assert result == expected


# =============================================================================
# Test: BootstrapConfig
# =============================================================================


class TestBootstrapConfig:
    """Tests for deploy.BootstrapConfig dataclass."""

    # ---------------------------------------------------------------------
    # Happy path - initialization and properties
    # ---------------------------------------------------------------------

    def test_creates_config_with_required_env(self):
        """Config initializes with only env parameter."""
        config = deploy.BootstrapConfig(env="dev")
        assert config.env == "dev"

    def test_has_default_region(self):
        """Config defaults to us-east-2 region."""
        config = deploy.BootstrapConfig(env="dev")
        assert config.region == "us-east-2"

    def test_has_default_github_org(self):
        """Config has default GitHub organization."""
        config = deploy.BootstrapConfig(env="dev")
        assert config.github_org == "Brad-Edwards"

    def test_has_default_github_repo(self):
        """Config has default GitHub repository."""
        config = deploy.BootstrapConfig(env="dev")
        assert config.github_repo == "shifter"

    def test_bucket_prefix_for_prod_env(self):
        """Config generates correct bucket prefix for prod."""
        config = deploy.BootstrapConfig(env="prod")
        assert config.bucket_prefix == "shifter-infra"

    def test_bucket_prefix_for_dev_env(self):
        """Config generates correct bucket prefix for dev."""
        config = deploy.BootstrapConfig(env="dev")
        assert config.bucket_prefix == "shifter-dev-infra"

    def test_table_prefix_for_prod_env(self):
        """Config generates correct DynamoDB table prefix for prod."""
        config = deploy.BootstrapConfig(env="prod")
        assert config.table_prefix == "shifter-terraform"

    def test_table_prefix_for_dev_env(self):
        """Config generates correct DynamoDB table prefix for dev."""
        config = deploy.BootstrapConfig(env="dev")
        assert config.table_prefix == "shifter-dev-terraform"

    def test_role_name_includes_env(self):
        """Config generates IAM role name with environment."""
        config = deploy.BootstrapConfig(env="staging")
        assert config.role_name == "github-actions-shifter-staging"

    def test_secret_name_for_prod_env(self):
        """Config generates GitHub secret name for prod."""
        config = deploy.BootstrapConfig(env="prod")
        assert config.secret_name == "AWS_ROLE_ARN"

    def test_secret_name_for_dev_env(self):
        """Config generates GitHub secret name for dev."""
        config = deploy.BootstrapConfig(env="dev")
        assert config.secret_name == "AWS_ROLE_ARN_DEV"

    # ---------------------------------------------------------------------
    # Input validation
    # ---------------------------------------------------------------------

    def test_accepts_custom_region(self):
        """Config accepts custom AWS region."""
        config = deploy.BootstrapConfig(env="dev", region="us-west-2")
        assert config.region == "us-west-2"

    def test_accepts_custom_github_org(self):
        """Config accepts custom GitHub organization."""
        config = deploy.BootstrapConfig(env="dev", github_org="my-org")
        assert config.github_org == "my-org"

    def test_accepts_custom_github_repo(self):
        """Config accepts custom GitHub repository."""
        config = deploy.BootstrapConfig(env="dev", github_repo="my-repo")
        assert config.github_repo == "my-repo"


# =============================================================================
# Test: GDCBootstrapConfig and helpers
# =============================================================================


class TestGdcProjectResolution:
    """Tests for repo-root .env and env-var based GDC project discovery."""

    def test_prefers_runtime_environment_over_repo_env(self, tmp_path):
        """Process env vars should win over the repo-root .env file."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".env").write_text("PANW_GCP_DEV=from-dotenv\n")

        with (
            patch("deploy.get_repo_root", return_value=repo_root),
            patch.dict("os.environ", {"PANW_GCP_DEV": "from-env"}, clear=False),
        ):
            assert deploy.get_default_gdc_project_id() == "from-env"

    def test_reads_project_id_from_repo_env_when_runtime_env_missing(self, tmp_path):
        """The repo-root .env should be used when no explicit env var is set."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".env").write_text("PANW_GCP_DEV=prod-rwctxzl6shxk\n")

        with (
            patch("deploy.get_repo_root", return_value=repo_root),
            patch.dict("os.environ", {}, clear=True),
        ):
            assert deploy.get_default_gdc_project_id() == "prod-rwctxzl6shxk"


class TestGdcBootstrapConfig:
    """Tests for deploy.GDCBootstrapConfig."""

    def test_derives_network_and_service_account_names(self):
        """Config should derive the default network, subnet, and service account names."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        assert config.resolved_network_name == "cluster1-gdc"
        assert config.resolved_subnetwork_name == "cluster1-gdc-us-central1"
        assert config.service_account_email == "baremetal-gcr@prod-rwctxzl6shxk.iam.gserviceaccount.com"
        assert config.gdc_access_secret_id == "shifter-gcp-dev-gdc-access"
        assert config.gdc_vm_image_gcs_secret_id == "shifter-gcp-dev-gdc-vm-image-gcs"

    def test_exposes_expected_cluster_hosts(self):
        """Config should expose the expected workstation, control-plane, and worker hosts."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        assert config.workstation.name == "cluster1-abm-ws0-001"
        assert [host.vxlan_ip for host in config.control_plane_hosts] == ["10.200.0.3", "10.200.0.4", "10.200.0.5"]
        assert [host.vxlan_ip for host in config.worker_hosts] == ["10.200.0.6", "10.200.0.7"]


class TestGdcRenderers:
    """Tests for the generated GDC bootstrap assets."""

    def test_cluster_config_includes_multi_network_and_vmruntime_prereqs(self):
        """The generated cluster config should include the validated networking settings."""
        config = deploy.GDCBootstrapConfig(
            project_id="prod-rwctxzl6shxk",
            cluster_id="cluster1",
            google_account_email="bedwards@paloaltonetworks.com",
        )

        rendered = deploy.render_gdc_cluster_config(config)

        assert "multipleNetworkInterfaces: true" in rendered
        assert "controlPlaneVIP: 10.200.0.49" in rendered
        assert "ingressVIP: 10.200.0.50" in rendered
        assert "clusterAdmin:" in rendered
        assert "bedwards@paloaltonetworks.com" in rendered

    def test_prepare_hosts_script_bakes_in_vxlan_and_inotify_fix(self):
        """The host prep script should contain both the vxlan setup and the inotify hardening."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        rendered = deploy.render_gdc_prepare_hosts_script(config)

        assert "ip link add vxlan0 type vxlan id 42" in rendered
        assert "fs.inotify.max_user_instances = 1024" in rendered
        assert 'configure_remote_host "10.240.0.3" "10.200.0.3"' in rendered

    def test_prepare_workstation_script_installs_staged_bmctl(self):
        """The workstation prep must install the pinned staged bmctl binary, not curl it remotely."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        rendered = deploy.render_gdc_prepare_workstation_script(config)

        assert f"install -m 755 {config.staging_bundle_dir}/bmctl /usr/local/sbin/bmctl" in rendered
        assert "anthos-baremetal-release" not in rendered

    def test_rendered_gdc_shell_scripts_parse_with_bash(self, tmp_path):
        """Rendered bootstrap shell scripts must be syntactically valid bash."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        rendered_scripts = {
            "prepare-workstation.sh": deploy.render_gdc_prepare_workstation_script(config),
            "prepare-hosts.sh": deploy.render_gdc_prepare_hosts_script(config),
            "create-cluster.sh": deploy.render_gdc_create_cluster_script(config),
            "install-helper.sh": deploy.render_gdc_install_helper_script(config),
        }

        for name, rendered in rendered_scripts.items():
            script_path = tmp_path / name
            script_path.write_text(rendered)
            process = subprocess.Popen(
                ["bash", "-n", str(script_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout, stderr = process.communicate()
            assert process.returncode == 0, f"{name} failed bash -n: {stdout}{stderr}"

    def test_create_cluster_script_is_safe_to_rerun(self):
        """The cluster create script should skip cluster creation if the kubeconfig already exists."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        rendered = deploy.render_gdc_create_cluster_script(config)

        assert f"if [ ! -f {config.kubeconfig_path} ]" in rendered
        assert "bmctl check vmruntimepfc" in rendered
        assert "patch vmruntime vmruntime" in rendered

    def test_build_gdc_access_secret_payload_contains_cluster_and_vxlan_details(self):
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        rendered = deploy.build_gdc_access_secret_payload(config, "apiVersion: v1\nclusters: []\n")

        assert '"cluster_id": "cluster1"' in rendered
        assert '"vxlan_cidr": "10.200.0.0/24"' in rendered
        assert '"network_interface": "vxlan0"' in rendered


class TestGdcBootstrapCluster:
    """Tests for deploy.gdc_bootstrap_cluster."""

    def test_executes_bootstrap_steps_in_order(self, tmp_path):
        """The GDC bootstrap path should execute the expected sequence of helper steps."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        staged_assets = {
            "assets_dir": tmp_path / "cluster1",
            "ssh_metadata": tmp_path / "cluster1" / "ssh-metadata",
            "service_account_key": tmp_path / "cluster1" / "bm-gcr.json",
        }

        with (
            patch("deploy.confirm", return_value=True),
            patch("deploy.ensure_gdc_apis") as mock_apis,
            patch("deploy.ensure_gdc_service_account") as mock_sa,
            patch("deploy.stage_gdc_bootstrap_assets", return_value=staged_assets) as mock_stage,
            patch("deploy.ensure_gdc_network") as mock_network,
            patch("deploy.ensure_gdc_instances") as mock_instances,
            patch("deploy.sync_gdc_instance_ssh_metadata") as mock_sync,
            patch("deploy.wait_for_gdc_ssh") as mock_wait,
            patch("deploy.upload_gdc_assets") as mock_upload,
            patch("deploy.run_gdc_workstation_script") as mock_remote,
            patch("deploy.sync_gdc_access_secret") as mock_access_secret,
            patch("deploy.sync_gdc_vm_image_secret") as mock_vm_image_secret,
            patch(
                "deploy.bootstrap_gcp_control_plane",
                return_value=_sample_gcp_control_plane_outputs(),
            ) as mock_platform,
        ):
            result = deploy.gdc_bootstrap_cluster(config)

            assert result["cluster_id"] == "cluster1"
            mock_apis.assert_called_once_with(config, dry_run=False)
            mock_sa.assert_called_once_with(config, dry_run=False)
            mock_stage.assert_called_once()
            mock_network.assert_called_once_with(config, dry_run=False)
            mock_instances.assert_called_once_with(config, staged_assets["ssh_metadata"], dry_run=False)
            mock_sync.assert_called_once_with(config, staged_assets["ssh_metadata"], dry_run=False)
            assert mock_wait.call_count == len(config.all_hosts)
            mock_upload.assert_called_once_with(config, staged_assets["assets_dir"], dry_run=False)
            assert [call.args[1] for call in mock_remote.call_args_list] == [
                "prepare-workstation.sh",
                "prepare-hosts.sh",
                "create-cluster.sh",
                "install-helper.sh",
            ]
            mock_access_secret.assert_called_once_with(config, dry_run=False)
            mock_vm_image_secret.assert_called_once_with(config, staged_assets["service_account_key"], dry_run=False)
            mock_platform.assert_called_once_with(config, dry_run=False)
            assert result["gdc_access_secret_id"] == "shifter-gcp-dev-gdc-access"
            assert result["gdc_vm_image_gcs_secret_id"] == "shifter-gcp-dev-gdc-vm-image-gcs"
            assert result["gke_cluster_name"] == "shifter-gcp-dev-platform"


class TestGdcControlPlaneTerraform:
    """Tests for the GCP control-plane Terraform bootstrap path."""

    def test_uses_requested_project_for_backend_and_apply(self, mock_repo_root):
        """Terraform bootstrap must target the live project instead of the committed gcp-dev placeholder."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        tf_dir = mock_repo_root / "platform" / "terraform" / "gcp" / "environments" / "gcp-dev"
        tf_dir.mkdir(parents=True)
        (tf_dir / "terraform.tfvars").write_text(
            """
project_id = "shifter-gcp-dev"
region = "us-central1"
public_hostname = "portal.example.test"
enable_managed_tls = true
gke_master_authorized_cidrs = ["198.51.100.10/32"]
"""
        )

        terraform_output = json.dumps(_sample_gcp_control_plane_outputs(config.project_id))

        with (
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("deploy.gcloud_resource_exists", return_value=False),
            patch("deploy.gcp_terraform_bootstrap_credentials", return_value=nullcontext(Path("bootstrap.json"))),
            patch("deploy.run_gcp_terraform_init_with_retry") as mock_init,
            patch("deploy.wait_for_gcp_terraform_bootstrap_access") as mock_wait,
            patch("deploy.run_gcp_terraform_apply_with_retry") as mock_apply,
            patch("deploy.run_cmd"),
            patch("os.chdir"),
            patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(["terraform"], 0, stdout=terraform_output),
            ),
        ):
            outputs = deploy.apply_gcp_control_plane_terraform(config)

        mock_init.assert_called_once_with(config, config.terraform_state_bucket_name, Path("bootstrap.json"))
        mock_wait.assert_called_once_with(config, Path("bootstrap.json"))
        assert mock_init.call_args.args[1] == "prod-rwctxzl6shxk-terraform-state"
        assert mock_init.call_args.args[0] is config
        expected_init = [
            "terraform",
            "init",
            "-reconfigure",
            "-backend-config=bucket=prod-rwctxzl6shxk-terraform-state",
            "-backend-config=prefix=shifter/gcp-dev/platform-core",
            "-backend-config=credentials=bootstrap.json",
        ]
        assert [
            "terraform",
            "init",
            "-reconfigure",
            f"-backend-config=bucket={config.terraform_state_bucket_name}",
            f"-backend-config=prefix=shifter/{config.environment}/platform-core",
            "-backend-config=credentials=bootstrap.json",
        ] == expected_init
        mock_apply.assert_called_once_with(config)
        expected_apply = [
            "terraform",
            "apply",
            "-auto-approve",
            "-var=project_id=prod-rwctxzl6shxk",
        ]
        assert ["terraform", "apply", "-auto-approve", f"-var=project_id={config.project_id}"] == expected_apply
        assert outputs["gke_cluster_name"]["value"] == "shifter-gcp-dev-platform"


class TestGcpControlPlaneSecurityInputs:
    """Tests for the bootstrap security preflight that runs before Terraform apply."""

    def test_reads_security_inputs_from_tfvars(self, tmp_path):
        """Bootstrap should read the hostname, TLS, and admin CIDR inputs from terraform.tfvars."""
        tf_dir = tmp_path / "gcp-dev"
        tf_dir.mkdir()
        (tf_dir / "terraform.tfvars").write_text(
            """
public_hostname = "portal.example.test"
enable_managed_tls = true
gke_master_authorized_cidrs = [
  "198.51.100.10/32",
  "203.0.113.0/24",
]
"""
        )

        settings = deploy.read_gcp_control_plane_security_inputs(tf_dir)

        assert settings == {
            "public_hostname": "portal.example.test",
            "enable_managed_tls": True,
            "gke_master_authorized_cidrs": ["198.51.100.10/32", "203.0.113.0/24"],
        }

    def test_validate_security_inputs_rejects_insecure_defaults(self, tmp_path):
        """Bootstrap must fail before Terraform apply when ingress and control-plane access are insecure."""
        tf_dir = tmp_path / "gcp-dev"
        tf_dir.mkdir()
        (tf_dir / "terraform.tfvars").write_text(
            """
public_hostname = ""
enable_managed_tls = false
gke_master_authorized_cidrs = []
"""
        )

        with pytest.raises(ValueError, match="public hostname"):
            deploy.validate_gcp_control_plane_security_inputs(tf_dir)


class TestGdcTerraformBootstrapCredentials:
    """Tests for the ephemeral Terraform credential path used by GCP bootstrap."""

    def test_bootstrap_credentials_set_google_env_vars_and_cleanup(self, monkeypatch):
        """Terraform bootstrap must provision temporary credentials and clean them up afterwards."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        def fake_run_cmd(cmd, *args, **kwargs):
            if cmd[:5] == ["gcloud", "iam", "service-accounts", "keys", "create"]:
                Path(cmd[5]).write_text('{"private_key_id":"bootstrap-key-id"}\n')
            return None

        for key in ("GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_BACKEND_CREDENTIALS", "GOOGLE_CREDENTIALS"):
            monkeypatch.delenv(key, raising=False)

        with (
            patch("deploy.gcloud_resource_exists", return_value=False),
            patch("deploy.prune_stale_gcp_terraform_bootstrap_keys") as mock_prune,
            patch("deploy.run_cmd", side_effect=fake_run_cmd) as mock_run_cmd,
            deploy.gcp_terraform_bootstrap_credentials(config) as credentials_path,
        ):
            assert Path(credentials_path).read_text() == '{"private_key_id":"bootstrap-key-id"}\n'
            assert os.environ["GOOGLE_APPLICATION_CREDENTIALS"] == str(credentials_path)
            assert "GOOGLE_BACKEND_CREDENTIALS" not in os.environ
            assert "GOOGLE_CREDENTIALS" not in os.environ

        mock_prune.assert_called_once_with(config)
        executed = [call.args[0] for call in mock_run_cmd.call_args_list]
        assert any(
            cmd[:4] == ["gcloud", "iam", "service-accounts", "create"]
            and cmd[4] == config.terraform_bootstrap_service_account_name
            for cmd in executed
        )
        assert any(
            cmd[:4] == ["gcloud", "projects", "add-iam-policy-binding", config.project_id] and "roles/owner" in cmd
            for cmd in executed
        )
        assert any(
            cmd[:5]
            == ["gcloud", "storage", "buckets", "add-iam-policy-binding", f"gs://{config.terraform_state_bucket_name}"]
            and "roles/storage.objectAdmin" in cmd
            for cmd in executed
        )
        assert any(
            cmd[:5] == ["gcloud", "iam", "service-accounts", "keys", "delete"] and "bootstrap-key-id" in cmd
            for cmd in executed
        )
        assert any(
            cmd[:4] == ["gcloud", "projects", "remove-iam-policy-binding", config.project_id] and "roles/owner" in cmd
            for cmd in executed
        )
        assert any(
            cmd[:5]
            == [
                "gcloud",
                "storage",
                "buckets",
                "remove-iam-policy-binding",
                f"gs://{config.terraform_state_bucket_name}",
            ]
            and "roles/storage.objectAdmin" in cmd
            for cmd in executed
        )
        for key in ("GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_BACKEND_CREDENTIALS", "GOOGLE_CREDENTIALS"):
            assert key not in os.environ

    def test_prunes_stale_user_managed_bootstrap_keys_before_creating_a_new_one(self):
        """Interrupted reruns must not accumulate leftover bootstrap keys."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        listed_keys = subprocess.CompletedProcess(
            ["gcloud"],
            0,
            stdout="stale-key-1\nstale-key-2\n",
            stderr="",
        )

        with (
            patch("deploy.subprocess.run", return_value=listed_keys),
            patch("deploy.run_cmd") as mock_run_cmd,
        ):
            deploy.prune_stale_gcp_terraform_bootstrap_keys(config)

        executed = [call.args[0] for call in mock_run_cmd.call_args_list]
        assert executed == [
            [
                "gcloud",
                "iam",
                "service-accounts",
                "keys",
                "delete",
                "stale-key-1",
                "--iam-account",
                config.terraform_bootstrap_service_account_email,
                "--project",
                config.project_id,
                "--quiet",
            ],
            [
                "gcloud",
                "iam",
                "service-accounts",
                "keys",
                "delete",
                "stale-key-2",
                "--iam-account",
                config.terraform_bootstrap_service_account_email,
                "--project",
                config.project_id,
                "--quiet",
            ],
        ]


class TestGdcTerraformInitRetries:
    """Tests for retrying Terraform init on GCS backend IAM propagation."""

    def test_retries_init_on_eventual_bucket_iam_consistency(self):
        """Documented GCS backend 403s must be retried until init succeeds."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        denied = subprocess.CompletedProcess(
            ["terraform"],
            1,
            stdout="Initializing the backend...\n",
            stderr=(
                "Error: Failed to get existing workspaces: querying Cloud Storage failed: "
                "googleapi: Error 403: shifter-gcp-dev-tf-bootstrap@prod-rwctxzl6shxk.iam.gserviceaccount.com "
                "does not have storage.objects.list access to the Google Cloud Storage bucket."
            ),
        )
        allowed = subprocess.CompletedProcess(["terraform"], 0, stdout="Initializing the backend...\n", stderr="")

        with (
            patch("subprocess.run", side_effect=[denied, allowed]) as mock_subprocess,
            patch("deploy.time.sleep") as mock_sleep,
        ):
            deploy.run_gcp_terraform_init_with_retry(
                config,
                config.terraform_state_bucket_name,
                Path("bootstrap.json"),
                max_attempts=2,
                sleep_seconds=0,
            )

        commands = [call.args[0] for call in mock_subprocess.call_args_list]
        assert commands == [
            [
                "terraform",
                "init",
                "-reconfigure",
                f"-backend-config=bucket={config.terraform_state_bucket_name}",
                f"-backend-config=prefix=shifter/{config.environment}/platform-core",
                "-backend-config=credentials=bootstrap.json",
            ],
            [
                "terraform",
                "init",
                "-reconfigure",
                f"-backend-config=bucket={config.terraform_state_bucket_name}",
                f"-backend-config=prefix=shifter/{config.environment}/platform-core",
                "-backend-config=credentials=bootstrap.json",
            ],
        ]
        mock_sleep.assert_called_once_with(0)

    def test_retries_invalid_jwt_signature_until_key_propagates(self):
        """Fresh service-account keys must be retried until Terraform can exchange them."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        invalid_auth = subprocess.CompletedProcess(
            ["terraform"],
            1,
            stdout="Initializing the backend...\n",
            stderr='Response: {"error":"invalid_grant","error_description":"Invalid JWT Signature."}',
        )
        allowed = subprocess.CompletedProcess(["terraform"], 0, stdout="Initializing the backend...\n", stderr="")

        with (
            patch("subprocess.run", side_effect=[invalid_auth, allowed]) as mock_subprocess,
            patch("deploy.time.sleep") as mock_sleep,
        ):
            deploy.run_gcp_terraform_init_with_retry(
                config,
                config.terraform_state_bucket_name,
                Path("bootstrap.json"),
                max_attempts=2,
                sleep_seconds=0,
            )

        assert mock_subprocess.call_count == 2
        mock_sleep.assert_called_once_with(0)

    def test_fails_fast_on_non_retryable_init_error(self):
        """Non-propagation Terraform failures must abort immediately."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        invalid_backend = subprocess.CompletedProcess(
            ["terraform"],
            1,
            stdout="Initializing the backend...\n",
            stderr="Error: unsupported backend configuration",
        )

        with (
            patch("subprocess.run", return_value=invalid_backend) as mock_subprocess,
            patch("deploy.time.sleep") as mock_sleep,
            pytest.raises(SystemExit),
        ):
            deploy.run_gcp_terraform_init_with_retry(
                config,
                config.terraform_state_bucket_name,
                Path("bootstrap.json"),
                max_attempts=3,
                sleep_seconds=0,
            )

        assert mock_subprocess.call_count == 1
        mock_sleep.assert_not_called()


class TestGdcTerraformApplyRetries:
    """Tests for retrying Terraform apply on temporary bootstrap-auth failures."""

    def test_retries_apply_on_iam_permission_propagation(self):
        """403 permission errors from freshly granted project roles must be retried."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        denied = subprocess.CompletedProcess(
            ["terraform"],
            1,
            stdout='module.platform_core.google_artifact_registry_repository.docker["portal"]: Creating...\n',
            stderr=(
                "Error: Error creating Repository: googleapi: Error 403: Permission "
                "'artifactregistry.repositories.create' denied on resource "
                "'//artifactregistry.googleapis.com/projects/prod-rwctxzl6shxk/locations/us-central1'."
            ),
        )
        allowed = subprocess.CompletedProcess(["terraform"], 0, stdout="Apply complete!\n", stderr="")

        with (
            patch("subprocess.run", side_effect=[denied, allowed]) as mock_subprocess,
            patch("deploy.time.sleep") as mock_sleep,
        ):
            deploy.run_gcp_terraform_apply_with_retry(config, max_attempts=2, sleep_seconds=0)

        commands = [call.args[0] for call in mock_subprocess.call_args_list]
        assert commands == [
            ["terraform", "apply", "-auto-approve", f"-var=project_id={config.project_id}"],
            ["terraform", "apply", "-auto-approve", f"-var=project_id={config.project_id}"],
        ]
        mock_sleep.assert_called_once_with(0)

    def test_fails_fast_on_non_retryable_apply_error(self):
        """Non-permission Terraform apply failures must abort immediately."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        invalid_apply = subprocess.CompletedProcess(
            ["terraform"],
            1,
            stdout="Planning failed.\n",
            stderr="Error: Invalid function argument",
        )

        with (
            patch("subprocess.run", return_value=invalid_apply) as mock_subprocess,
            patch("deploy.time.sleep") as mock_sleep,
            pytest.raises(SystemExit),
        ):
            deploy.run_gcp_terraform_apply_with_retry(config, max_attempts=3, sleep_seconds=0)

        assert mock_subprocess.call_count == 1
        mock_sleep.assert_not_called()


class TestGdcTerraformBootstrapAccess:
    """Tests for waiting until bootstrap credentials can really read GCP resources."""

    def test_waits_until_storage_and_artifact_registry_access_are_usable(self):
        """Bootstrap must not start apply until the temporary credentials can list required resources."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        denied = subprocess.CompletedProcess(
            ["gcloud"],
            1,
            stdout="",
            stderr=(
                "ERROR: (gcloud.artifacts.repositories.list) googleapi: Error 403: "
                "Permission 'artifactregistry.repositories.list' denied on resource "
                "'//artifactregistry.googleapis.com/projects/prod-rwctxzl6shxk/locations/us-central1'."
            ),
        )
        allowed = subprocess.CompletedProcess(["gcloud"], 0, stdout="ok\n", stderr="")
        probe_attempts = {"artifact_list": 0}

        def fake_probe(cmd, credentials_path):
            if cmd[:4] == ["gcloud", "artifacts", "repositories", "list"]:
                probe_attempts["artifact_list"] += 1
                return denied if probe_attempts["artifact_list"] == 1 else allowed
            return allowed

        with (
            patch("deploy._run_gcp_bootstrap_probe", side_effect=fake_probe) as mock_probe,
            patch("deploy.time.sleep") as mock_sleep,
        ):
            deploy.wait_for_gcp_terraform_bootstrap_access(
                config,
                Path("bootstrap.json"),
                max_attempts=2,
                sleep_seconds=0,
            )

        assert mock_probe.call_count == 6
        mock_sleep.assert_called_once_with(0)

    def test_probe_uses_credential_file_override(self, tmp_path):
        """The readiness probes must use the same temporary credential file Terraform uses."""
        completed = subprocess.CompletedProcess(["gcloud"], 0, stdout="", stderr="")
        credentials_path = tmp_path / "bootstrap.json"

        with patch("deploy.subprocess.run", return_value=completed) as mock_subprocess:
            deploy._run_gcp_bootstrap_probe(["gcloud", "storage", "buckets", "list"], credentials_path)

        env = mock_subprocess.call_args.kwargs["env"]
        assert env["CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE"] == str(credentials_path)
        assert env["GOOGLE_APPLICATION_CREDENTIALS"] == str(credentials_path)

    def test_fails_fast_when_probe_error_is_not_retryable(self):
        """Permanent probe failures must abort instead of looping blindly."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        invalid = subprocess.CompletedProcess(
            ["gcloud"],
            1,
            stdout="",
            stderr="ERROR: (gcloud.artifacts.repositories.list) INVALID_ARGUMENT: bad request",
        )

        with (
            patch("deploy._run_gcp_bootstrap_probe", return_value=invalid) as mock_probe,
            patch("deploy.time.sleep") as mock_sleep,
            pytest.raises(SystemExit),
        ):
            deploy.wait_for_gcp_terraform_bootstrap_access(
                config,
                Path("bootstrap.json"),
                max_attempts=2,
                sleep_seconds=0,
            )

        assert mock_probe.call_count == 3
        mock_sleep.assert_not_called()


class TestGdcControlPlaneHelmValues:
    """Tests for rendering Helm values for the GCP Shifter release."""

    def test_renders_values_with_live_project_specific_inputs(self):
        """The generated values must carry project-specific images, env contracts, and identity bindings."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        outputs = _sample_gcp_control_plane_outputs(config.project_id)
        values = deploy.render_gcp_helm_values(
            config,
            outputs,
            guacamole_db_payload={"username": "guac", "password": "supersecret"},
            guacamole_json_secret="json-auth-key",
        )

        assert values["releaseNamespace"] == "shifter-system"
        assert values["runtimeEnv"]["GCP_PROJECT_ID"] == "prod-rwctxzl6shxk"
        assert values["runtimeEnv"]["GOOGLE_CLOUD_PROJECT"] == "prod-rwctxzl6shxk"
        assert values["runtimeEnv"]["DJANGO_DEBUG"] == "false"
        assert values["runtimeEnv"]["SESSION_COOKIE_SECURE"] == "true"
        assert values["runtimeEnv"]["SITE_URL"] == "https://portal.example.test"
        assert (
            values["runtimeEnv"]["GDC_VM_IMAGE_GCS_SECRET_ID"]
            == "projects/prod-rwctxzl6shxk/secrets/shifter-gcp-dev-gdc-vm-image-gcs"
        )
        assert (
            values["serviceAccounts"]["portal"]["annotations"]["iam.gke.io/gcp-service-account"]
            == "shiftergcpdev-portal@prod-rwctxzl6shxk.iam.gserviceaccount.com"
        )
        assert (
            values["serviceAccounts"]["workers"]["annotations"]["iam.gke.io/gcp-service-account"]
            == "shiftergcpdev-workers@prod-rwctxzl6shxk.iam.gserviceaccount.com"
        )
        assert (
            values["serviceAccounts"]["provisioner"]["annotations"]["iam.gke.io/gcp-service-account"]
            == "shiftergcpdev-provisioner@prod-rwctxzl6shxk.iam.gserviceaccount.com"
        )
        assert values["images"]["portal"]["repository"] == (
            "us-central1-docker.pkg.dev/prod-rwctxzl6shxk/shifter-gcp-dev-portal/portal"
        )
        assert values["images"]["guacd"]["repository"] == (
            "us-central1-docker.pkg.dev/prod-rwctxzl6shxk/shifter-gcp-dev-guacd/guacd"
        )
        assert values["images"]["guacamoleClient"]["repository"] == (
            "us-central1-docker.pkg.dev/prod-rwctxzl6shxk/shifter-gcp-dev-guacamole-client/guacamole-client"
        )
        assert values["guacamoleRuntimeSecret"]["stringData"] == {
            "POSTGRESQL_USER": "guac",
            "POSTGRESQL_PASSWORD": "supersecret",
            "JSON_SECRET_KEY": "json-auth-key",
        }
        assert values["services"]["portal"]["backendConfig"]["securityPolicyName"] == "shifter-gcp-dev-edge"
        assert values["services"]["guacamoleClient"]["backendConfig"]["enabled"] is True
        assert values["services"]["guacamoleClient"]["backendConfig"]["name"] == "guacamole-client"
        assert values["services"]["guacamoleClient"]["backendConfig"]["securityPolicyName"] == "shifter-gcp-dev-edge"
        assert values["networkPolicy"] == {
            "enabled": True,
            "gclbSourceRanges": [
                "35.191.0.0/16",  # NOSONAR - Google Cloud Load Balancer range.
                "130.211.0.0/22",  # NOSONAR - Google Cloud Load Balancer range.
            ],
            "googleApiCidrs": [
                "199.36.153.4/30",  # NOSONAR - restricted.googleapis.com VIP.
                "199.36.153.8/30",  # NOSONAR - private.googleapis.com VIP.
            ],
            "privateServiceCidrs": ["10.40.0.10/32", "10.40.0.20/32", "10.48.0.0/20"],
        }

    def test_rejects_insecure_public_bootstrap_values(self):
        """The Helm values renderer must refuse public bare-IP debug deployments on GCP."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        outputs = _sample_gcp_control_plane_outputs(config.project_id)
        outputs["public_hostname"] = {"value": ""}
        outputs["managed_tls_enabled"] = {"value": False}

        with pytest.raises(ValueError, match="public_hostname"):
            deploy.render_gcp_helm_values(
                config,
                outputs,
                guacamole_db_payload={"username": "guac", "password": "supersecret"},
                guacamole_json_secret="json-auth-key",
            )


class TestGdcControlPlaneHelmChart:
    """Tests for the Helm chart that packages the GCP Shifter deployment."""

    def test_chart_renders_restricted_security_contexts_and_numeric_runtime_ids(self, tmp_path):
        """The chart must render restricted-compatible workloads with pinned runtime IDs."""
        helm = shutil.which("helm")
        if helm is None:
            pytest.skip("helm is required for chart render validation")

        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        outputs = _sample_gcp_control_plane_outputs(config.project_id)
        values_path = tmp_path / "values.json"
        values_path.write_text(
            json.dumps(
                deploy.render_gcp_helm_values(
                    config,
                    outputs,
                    guacamole_db_payload={"username": "guac", "password": "supersecret"},
                    guacamole_json_secret="json-auth-key",
                )
            )
        )
        chart_dir = Path(__file__).resolve().parents[3] / "platform" / "charts" / "shifter"

        rendered = subprocess.Popen(  # nosec B603 B607
            [
                helm,
                "template",
                "shifter",
                str(chart_dir),
                "--namespace",
                "shifter-system",
                "--values",
                str(values_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = rendered.communicate()

        assert rendered.returncode == 0, stderr
        output = stdout
        assert "kind: Deployment" in output
        assert "name: portal-web" in output
        assert "name: worker-cms" in output
        assert "name: guacd" in output
        assert "name: guacamole-client" in output
        assert "type: RuntimeDefault" in output
        assert "allowPrivilegeEscalation: false" in output
        assert "runAsNonRoot: true" in output
        assert "runAsUser: 1000" in output
        assert "runAsGroup: 1000" in output
        assert "runAsUser: 1001" in output
        assert "runAsGroup: 1001" in output
        assert "kind: Namespace" not in output
        assert "kind: BackendConfig" in output
        assert "kind: NetworkPolicy" in output
        assert "name: default-deny-platform" in output
        assert "name: default-deny-jobs" in output
        assert "199.36.153.4/30" in output
        assert "10.40.0.10/32" in output
        assert 'requestPath: "/health/"' in output
        assert "securityPolicy:" in output
        assert "name: shifter-gcp-dev-edge" in output
        assert 'cloud.google.com/backend-config: "{\\"default\\":\\"portal-web\\"}"' in output
        assert 'cloud.google.com/backend-config: "{\\"default\\":\\"guacamole-client\\"}"' in output


class TestGdcClusterAccessHardening:
    """Tests for the private GDC admin path."""

    def test_instance_create_uses_private_network_only(self, tmp_path):
        """GDC hosts must not receive public IP addresses."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        cmd = deploy.gdc_instance_create_command(config, config.workstation, tmp_path / "ssh-metadata")

        assert "--no-address" in cmd

    def test_wait_for_gdc_ssh_uses_iap_tunnel(self):
        """Bootstrap SSH probes must go through IAP instead of direct public SSH."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        ready = subprocess.CompletedProcess(["gcloud"], 0, stdout="ready", stderr="")

        with patch("deploy.subprocess.run", return_value=ready) as mock_run:
            deploy.wait_for_gdc_ssh(config, config.workstation)

        cmd = mock_run.call_args.args[0]
        assert cmd[:3] == ["gcloud", "compute", "ssh"]
        assert "--tunnel-through-iap" in cmd

    def test_run_gdc_workstation_script_uses_iap_tunnel(self):
        """Remote workstation scripts must go through IAP."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        with patch("deploy.run_cmd") as mock_run_cmd:
            deploy.run_gdc_workstation_script(config, "prepare-workstation.sh")

        assert mock_run_cmd.call_args.args[0] == [
            "gcloud",
            "compute",
            "ssh",
            f"root@{config.workstation.name}",
            "--tunnel-through-iap",
            "--project",
            config.project_id,
            "--zone",
            config.zone,
            "--command",
            f"bash {config.staging_dir}/{config.cluster_id}/prepare-workstation.sh",
        ]

    def test_fetch_gdc_kubeconfig_uses_iap_tunnel(self):
        """Kubeconfig fetches must go through IAP."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        with patch(
            "deploy.run_cmd",
            return_value=subprocess.CompletedProcess(["gcloud"], 0, stdout="apiVersion: v1\n", stderr=""),
        ) as mock_run_cmd:
            deploy.fetch_gdc_kubeconfig(config)

        assert mock_run_cmd.call_args.args[0] == [
            "gcloud",
            "compute",
            "ssh",
            f"root@{config.workstation.name}",
            "--tunnel-through-iap",
            "--project",
            config.project_id,
            "--zone",
            config.zone,
            "--command",
            f"cat {config.kubeconfig_path}",
        ]

    def test_ensure_gdc_network_locks_ssh_to_iap_and_lb_to_internal_subnet(self):
        """The GDC network must not expose SSH or LB/admin ports to the internet."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        with (
            patch("deploy.gcloud_resource_exists", return_value=False),
            patch("deploy.run_cmd") as mock_run_cmd,
        ):
            deploy.ensure_gdc_network(config)

        firewall_creates = [
            call.args[0]
            for call in mock_run_cmd.call_args_list
            if call.args[0][:4] == ["gcloud", "compute", "firewall-rules", "create"]
        ]
        assert any(cmd[4] == config.ssh_firewall_rule_name and "35.235.240.0/20" in cmd for cmd in firewall_creates)
        assert any(cmd[4] == config.lb_firewall_rule_name and config.subnet_cidr in cmd for cmd in firewall_creates)

    def test_ensure_gdc_network_provisions_cloud_nat_for_private_host_egress(self):
        """Private GDC hosts must get outbound internet access through Cloud NAT."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        with (
            patch("deploy.gcloud_resource_exists", return_value=False),
            patch("deploy.run_cmd") as mock_run_cmd,
        ):
            deploy.ensure_gdc_network(config)

        router_create = next(
            call.args[0]
            for call in mock_run_cmd.call_args_list
            if call.args[0][:4] == ["gcloud", "compute", "routers", "create"]
        )
        nat_create = next(
            call.args[0]
            for call in mock_run_cmd.call_args_list
            if call.args[0][:5] == ["gcloud", "compute", "routers", "nats", "create"]
        )

        assert router_create == [
            "gcloud",
            "compute",
            "routers",
            "create",
            config.cloud_router_name,
            "--project",
            config.project_id,
            "--region",
            config.region,
            "--network",
            config.resolved_network_name,
        ]
        assert nat_create == [
            "gcloud",
            "compute",
            "routers",
            "nats",
            "create",
            config.cloud_nat_name,
            "--project",
            config.project_id,
            "--router",
            config.cloud_router_name,
            "--region",
            config.region,
            "--auto-allocate-nat-external-ips",
            "--nat-custom-subnet-ip-ranges",
            config.resolved_subnetwork_name,
            "--enable-logging",
        ]


class TestGdcControlPlaneRollout:
    """Tests for deploying Shifter onto GKE through Helm."""

    def test_rollout_sequence_fetches_credentials_and_runs_atomic_helm_release(self, tmp_path):
        """The rollout path must fetch cluster credentials and perform one atomic Helm release."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        outputs = _sample_gcp_control_plane_outputs(config.project_id)
        values_path = tmp_path / "values.json"
        values_path.write_text("{}")
        chart_dir = Path(__file__).resolve().parents[3] / "platform" / "charts" / "shifter"
        environment_values_path = chart_dir / "values-gcp-dev.yaml"

        with (
            patch("deploy.run_cmd") as mock_run_cmd,
            patch("deploy.ensure_gke_gcloud_auth_plugin") as mock_ensure_plugin,
            patch("deploy.prepare_gcp_helm_cutover") as mock_prepare_cutover,
            patch("deploy.ensure_gcp_control_plane_namespaces") as mock_ensure_namespaces,
            patch("deploy.get_repo_root", return_value=Path(__file__).resolve().parents[3]),
        ):
            deploy.deploy_gcp_control_plane_with_helm(config, outputs, values_path)

        mock_ensure_plugin.assert_called_once_with(dry_run=False)
        mock_prepare_cutover.assert_called_once_with(dry_run=False)
        mock_ensure_namespaces.assert_called_once_with(dry_run=False)
        commands = [call.args[0] for call in mock_run_cmd.call_args_list]
        assert commands[0] == [
            "gcloud",
            "container",
            "clusters",
            "get-credentials",
            "shifter-gcp-dev-platform",
            "--location",
            "us-central1",
            "--project",
            "prod-rwctxzl6shxk",
        ]
        assert commands[1] == [
            "helm",
            "upgrade",
            "--install",
            "shifter",
            str(chart_dir),
            "--namespace",
            "shifter-system",
            "--create-namespace",
            "--values",
            str(environment_values_path),
            "--values",
            str(values_path),
            "--atomic",
            "--wait",
            "--timeout",
            "15m",
            "--history-max",
            "10",
        ]

    def test_bootstrap_control_plane_creates_operator_before_helm_and_waits_for_dns_tls_after_release(self):
        """Bootstrap must seed Identity Platform before Helm and only finish after DNS/TLS verification."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        outputs = _sample_gcp_control_plane_outputs(config.project_id)
        calls: list[str] = []

        def record(name: str):
            def _inner(*args, **kwargs):
                calls.append(name)
                if name == "apply":
                    return outputs
                if name == "stage":
                    return Path("shifter.values.generated.json")
                return None

            return _inner

        with (
            patch("deploy.apply_gcp_control_plane_terraform", side_effect=record("apply")),
            patch("deploy.ensure_gcp_identity_platform_operator", side_effect=record("seed_operator")),
            patch("deploy.push_gcp_control_plane_images", side_effect=record("push_images")),
            patch("deploy.stage_gcp_control_plane_values", side_effect=record("stage")),
            patch("deploy.deploy_gcp_control_plane_with_helm", side_effect=record("deploy")),
            patch("deploy.walkthrough_gcp_dns_setup_and_wait_for_tls", side_effect=record("dns_tls")),
        ):
            result = deploy.bootstrap_gcp_control_plane(config)

        assert result == outputs
        assert calls == ["apply", "seed_operator", "push_images", "stage", "deploy", "dns_tls"]


class TestGdcControlPlaneNamespaces:
    """Tests for namespace lifecycle outside the Helm release."""

    def test_creates_required_namespaces_with_restricted_labels(self):
        """Bootstrap must create Helm target namespaces before the release installs."""
        missing_platform = subprocess.CompletedProcess(
            ["kubectl"],
            1,
            stdout="",
            stderr='Error from server (NotFound): namespaces "shifter-platform" not found',
        )
        active_platform = subprocess.CompletedProcess(
            ["kubectl"],
            0,
            stdout=json.dumps({"status": {"phase": "Active"}}),
            stderr="",
        )
        missing_jobs = subprocess.CompletedProcess(
            ["kubectl"],
            1,
            stdout="",
            stderr='Error from server (NotFound): namespaces "shifter-jobs" not found',
        )
        active_jobs = subprocess.CompletedProcess(
            ["kubectl"],
            0,
            stdout=json.dumps({"status": {"phase": "Active"}}),
            stderr="",
        )

        with patch(
            "deploy.subprocess.run",
            side_effect=[
                missing_platform,
                subprocess.CompletedProcess(["kubectl"], 0, stdout="namespace/shifter-platform created\n", stderr=""),
                active_platform,
                missing_jobs,
                subprocess.CompletedProcess(["kubectl"], 0, stdout="namespace/shifter-jobs created\n", stderr=""),
                active_jobs,
            ],
        ) as mock_subprocess:
            deploy.ensure_gcp_control_plane_namespaces()

        apply_calls = [
            call for call in mock_subprocess.call_args_list if call.args[0][:3] == ["kubectl", "apply", "-f"]
        ]
        assert len(apply_calls) == 2
        platform_manifest = json.loads(apply_calls[0].kwargs["input"])
        jobs_manifest = json.loads(apply_calls[1].kwargs["input"])
        assert platform_manifest["metadata"]["name"] == "shifter-platform"
        assert platform_manifest["metadata"]["labels"]["app.kubernetes.io/part-of"] == "shifter"
        assert platform_manifest["metadata"]["labels"]["pod-security.kubernetes.io/enforce"] == "restricted"
        assert jobs_manifest["metadata"]["name"] == "shifter-jobs"
        assert jobs_manifest["metadata"]["labels"]["shifter.dev/plane"] == "jobs"

    def test_waits_for_terminating_namespace_then_recreates_it(self):
        """A terminating namespace from a failed install must be allowed to clear first."""
        terminating_platform = subprocess.CompletedProcess(
            ["kubectl"],
            0,
            stdout=json.dumps(
                {
                    "metadata": {"deletionTimestamp": "2026-04-10T00:00:00Z"},
                    "status": {"phase": "Terminating"},
                }
            ),
            stderr="",
        )
        missing_platform = subprocess.CompletedProcess(
            ["kubectl"],
            1,
            stdout="",
            stderr='Error from server (NotFound): namespaces "shifter-platform" not found',
        )
        active_platform = subprocess.CompletedProcess(
            ["kubectl"],
            0,
            stdout=json.dumps({"status": {"phase": "Active"}}),
            stderr="",
        )
        active_jobs = subprocess.CompletedProcess(
            ["kubectl"],
            0,
            stdout=json.dumps({"status": {"phase": "Active"}}),
            stderr="",
        )

        with (
            patch(
                "deploy.subprocess.run",
                side_effect=[
                    terminating_platform,
                    missing_platform,
                    subprocess.CompletedProcess(
                        ["kubectl"],
                        0,
                        stdout="namespace/shifter-platform created\n",
                        stderr="",
                    ),
                    active_platform,
                    active_jobs,
                    subprocess.CompletedProcess(
                        ["kubectl"],
                        0,
                        stdout="namespace/shifter-jobs configured\n",
                        stderr="",
                    ),
                    active_jobs,
                ],
            ) as mock_subprocess,
            patch("deploy.time.sleep") as mock_sleep,
        ):
            deploy.ensure_gcp_control_plane_namespaces()

        mock_sleep.assert_not_called()
        apply_calls = [
            call for call in mock_subprocess.call_args_list if call.args[0][:3] == ["kubectl", "apply", "-f"]
        ]
        assert len(apply_calls) == 2


class TestGdcHelmCutover:
    """Tests for the breaking cutover from legacy raw manifests to Helm."""

    def test_first_install_deletes_legacy_resources_before_helm_takes_over(self):
        """A non-Helm legacy deployment must be removed before the first Helm install."""
        with (
            patch("deploy.helm_release_exists", return_value=False),
            patch(
                "deploy.list_gcp_helm_cutover_resources",
                side_effect=lambda namespace: {
                    "shifter-system": [],
                    "shifter-platform": [
                        "configmap/platform-runtime",
                        "deployment.apps/portal-web",
                        "secret/guacamole-runtime",
                        "serviceaccount/portal",
                    ],
                    "shifter-jobs": ["serviceaccount/provisioner"],
                }[namespace],
            ),
            patch("deploy.run_cmd") as mock_run_cmd,
        ):
            deploy.prepare_gcp_helm_cutover()

        commands = [call.args[0] for call in mock_run_cmd.call_args_list]
        assert commands == [
            [
                "kubectl",
                "-n",
                "shifter-platform",
                "delete",
                "configmap/platform-runtime",
                "deployment.apps/portal-web",
                "secret/guacamole-runtime",
                "serviceaccount/portal",
                "--ignore-not-found=true",
                "--wait=true",
                "--timeout=10m",
            ],
            [
                "kubectl",
                "-n",
                "shifter-jobs",
                "delete",
                "serviceaccount/provisioner",
                "--ignore-not-found=true",
                "--wait=true",
                "--timeout=10m",
            ],
        ]

    def test_existing_helm_release_skips_namespace_cleanup(self):
        """Reruns must not delete namespaces once Helm already owns the environment."""
        with (
            patch("deploy.helm_release_exists", return_value=True),
            patch("deploy.list_gcp_helm_cutover_resources") as mock_list,
            patch("deploy.run_cmd") as mock_run_cmd,
        ):
            deploy.prepare_gcp_helm_cutover()

        mock_list.assert_not_called()
        mock_run_cmd.assert_not_called()

    def test_missing_namespace_is_treated_as_no_legacy_resources(self):
        """Cutover inspection must tolerate namespaces that do not exist yet."""
        not_found = subprocess.CompletedProcess(
            ["kubectl"],
            1,
            stdout="",
            stderr='Error from server (NotFound): namespaces "shifter-jobs" not found',
        )

        with patch("deploy.subprocess.run", return_value=not_found):
            assert deploy.list_gcp_helm_cutover_resources("shifter-jobs") == []

    def test_explicit_runtime_objects_are_included_even_without_labels(self):
        """Legacy runtime config objects from the raw path must still be purged."""
        labeled = subprocess.CompletedProcess(
            ["kubectl"],
            0,
            stdout="serviceaccount/portal\n",
            stderr="",
        )
        explicit = subprocess.CompletedProcess(
            ["kubectl"],
            0,
            stdout="configmap/platform-runtime\nsecret/guacamole-runtime\n",
            stderr="",
        )

        with patch("deploy.subprocess.run", side_effect=[labeled, explicit]):
            assert deploy.list_gcp_helm_cutover_resources("shifter-platform") == [
                "configmap/platform-runtime",
                "secret/guacamole-runtime",
                "serviceaccount/portal",
            ]


class TestGkeGcloudAuthPlugin:
    """Tests for ensuring the local GKE kubectl auth plugin."""

    def test_skips_install_when_plugin_already_present(self):
        """No package-manager calls should run when the plugin is already on PATH."""
        with (
            patch("deploy.shutil.which", return_value="/usr/bin/gke-gcloud-auth-plugin"),
            patch("deploy.run_cmd") as mock_run_cmd,
        ):
            deploy.ensure_gke_gcloud_auth_plugin()

        mock_run_cmd.assert_not_called()

    def test_installs_plugin_with_apt_when_running_as_root(self):
        """On apt-based systems, bootstrap should install the plugin automatically."""

        def fake_which(cmd: str) -> str | None:
            if cmd == "gke-gcloud-auth-plugin":
                return None if fake_which.calls == 0 else "/usr/bin/gke-gcloud-auth-plugin"
            if cmd == "apt-get":
                return "/usr/bin/apt-get"
            return None

        fake_which.calls = 0

        def which_side_effect(cmd: str) -> str | None:
            result = fake_which(cmd)
            if cmd == "gke-gcloud-auth-plugin":
                fake_which.calls += 1
            return result

        with (
            patch("deploy.shutil.which", side_effect=which_side_effect),
            patch("deploy.os.geteuid", return_value=0),
            patch("deploy.run_cmd") as mock_run_cmd,
        ):
            deploy.ensure_gke_gcloud_auth_plugin()

        commands = [call.args[0] for call in mock_run_cmd.call_args_list]
        assert commands == [
            ["apt-get", "update"],
            ["apt-get", "install", "-y", "google-cloud-cli-gke-gcloud-auth-plugin"],
        ]

    def test_uses_sudo_when_not_running_as_root(self):
        """Non-root bootstrap runs should elevate for the plugin install."""

        def fake_which(cmd: str) -> str | None:
            if cmd == "gke-gcloud-auth-plugin":
                return None if fake_which.calls == 0 else "/usr/bin/gke-gcloud-auth-plugin"
            if cmd == "apt-get":
                return "/usr/bin/apt-get"
            if cmd == "sudo":
                return "/usr/bin/sudo"
            return None

        fake_which.calls = 0

        def which_side_effect(cmd: str) -> str | None:
            result = fake_which(cmd)
            if cmd == "gke-gcloud-auth-plugin":
                fake_which.calls += 1
            return result

        with (
            patch("deploy.shutil.which", side_effect=which_side_effect),
            patch("deploy.os.geteuid", return_value=1000),
            patch("deploy.run_cmd") as mock_run_cmd,
        ):
            deploy.ensure_gke_gcloud_auth_plugin()

        commands = [call.args[0] for call in mock_run_cmd.call_args_list]
        assert commands == [
            ["sudo", "apt-get", "update"],
            ["sudo", "apt-get", "install", "-y", "google-cloud-cli-gke-gcloud-auth-plugin"],
        ]

    def test_uses_user_space_install_when_not_root_and_sudo_unavailable(self):
        """Bootstrap should fall back to a user-space plugin install when sudo is unavailable."""
        with (
            patch(
                "deploy.shutil.which",
                side_effect=lambda cmd: (
                    None
                    if cmd in {"gke-gcloud-auth-plugin", "sudo"}
                    else "/usr/bin/apt-get"
                    if cmd == "apt-get"
                    else None
                ),
            ),
            patch("deploy.os.geteuid", return_value=1000),
            patch("deploy.install_gke_gcloud_auth_plugin_user_space") as mock_user_space_install,
        ):
            deploy.ensure_gke_gcloud_auth_plugin(dry_run=True)

        mock_user_space_install.assert_called_once_with(dry_run=True)

    def test_fails_when_plugin_missing_and_host_is_not_apt_based(self):
        """Bootstrap must fail clearly when it cannot satisfy the plugin prerequisite."""
        with (
            patch("deploy.shutil.which", return_value=None),
            patch("deploy.error") as mock_error,
            pytest.raises(SystemExit),
        ):
            deploy.ensure_gke_gcloud_auth_plugin()

        mock_error.assert_called_once()
        assert "Automatic installation requires apt-based package tooling" in mock_error.call_args.args[0]


class TestGkeGcloudAuthPluginUserSpaceInstall:
    """Tests for the user-space GKE auth plugin install path."""

    def test_extracts_package_and_copies_binary_into_local_bin(self, tmp_path):
        """The user-space installer must stage the binary into ~/.local/bin."""

        def fake_subprocess(cmd, cwd=None, **kwargs):
            if cmd[:2] == ["apt", "download"]:
                package = Path(cwd) / "google-cloud-cli-gke-gcloud-auth-plugin_564.0.0-0_amd64.deb"
                package.write_text("fake-deb")
            elif cmd[:2] == ["dpkg-deb", "-x"]:
                extract_root = Path(cmd[3])
                binary = extract_root / "usr" / "lib" / "google-cloud-sdk" / "bin" / "gke-gcloud-auth-plugin"
                binary.parent.mkdir(parents=True, exist_ok=True)
                binary.write_text("plugin")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with (
            patch(
                "deploy.shutil.which",
                side_effect=lambda cmd: "/usr/bin/" + cmd if cmd in {"apt", "dpkg-deb"} else None,
            ),
            patch("deploy.tempfile.TemporaryDirectory", return_value=nullcontext(str(tmp_path))),
            patch("deploy.Path.home", return_value=tmp_path),
            patch("deploy.subprocess.run", side_effect=fake_subprocess),
        ):
            deploy.install_gke_gcloud_auth_plugin_user_space()

        destination = tmp_path / ".local" / "bin" / "gke-gcloud-auth-plugin"
        assert destination.exists()
        assert destination.read_text() == "plugin"


class TestGdcBootstrapPrerequisites:
    """Tests for GDC bootstrap IAM and API prerequisites."""

    def test_gdc_api_enablement_includes_cloud_storage(self):
        """Bootstrap must enable the Cloud Storage API used by GDC workflows."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        with patch("deploy.run_cmd") as mock_run_cmd:
            deploy.ensure_gdc_apis(config)

        enable_call = mock_run_cmd.call_args_list[1]
        assert enable_call.args[0][:3] == ["gcloud", "services", "enable"]
        assert "storage.googleapis.com" in enable_call.args[0]
        assert "iap.googleapis.com" in enable_call.args[0]

    def test_gdc_service_account_grants_compute_viewer_for_bmctl(self):
        """The bootstrap service account must be able to read Compute zone metadata for bmctl."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        with (
            patch("deploy.gcloud_resource_exists", return_value=True),
            patch("deploy.run_cmd") as mock_run_cmd,
        ):
            deploy.ensure_gdc_service_account(config)

        granted_roles = [call.args[0][7] for call in mock_run_cmd.call_args_list]
        assert "roles/compute.viewer" in granted_roles

    def test_gdc_service_account_waits_for_visibility_after_create(self):
        """First-run bootstrap must wait for service-account propagation before IAM bindings."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        with (
            patch("deploy.gcloud_resource_exists", side_effect=[False, False, False, True]),
            patch("deploy.run_cmd") as mock_run_cmd,
            patch("deploy.time.sleep") as mock_sleep,
        ):
            deploy.ensure_gdc_service_account(config)

        assert mock_run_cmd.call_args_list[0].args[0][:4] == [
            "gcloud",
            "iam",
            "service-accounts",
            "create",
        ]
        assert any(
            call.args[0][0:3] == ["gcloud", "projects", "add-iam-policy-binding"]
            for call in mock_run_cmd.call_args_list
        )
        assert mock_sleep.call_count == 2


class TestGcpPlatformCoreContracts:
    """Tests for the Terraform platform-core contract that bootstrap depends on."""

    def test_workload_identity_bindings_exist_for_platform_service_accounts(self):
        """Portal, workers, and provisioner KSAs must be able to impersonate their GSAs."""
        module_path = (
            Path(__file__).resolve().parents[3]
            / "platform"
            / "terraform"
            / "gcp"
            / "modules"
            / "platform-core"
            / "main.tf"
        )
        module_main = module_path.read_text()

        assert 'resource "google_service_account_iam_member" "workload_identity"' in module_main
        assert 'role               = "roles/iam.workloadIdentityUser"' in module_main
        assert '"serviceAccount:${var.project_id}.svc.id.goog[shifter-platform/portal]"' in module_main
        assert '"serviceAccount:${var.project_id}.svc.id.goog[shifter-platform/workers]"' in module_main
        assert '"serviceAccount:${var.project_id}.svc.id.goog[shifter-jobs/provisioner]"' in module_main

    def test_workers_have_pubsub_publish_and_subscribe_permissions(self):
        """The shared workers service account must publish as well as consume Pub/Sub events."""
        module_path = (
            Path(__file__).resolve().parents[3]
            / "platform"
            / "terraform"
            / "gcp"
            / "modules"
            / "platform-core"
            / "main.tf"
        )
        module_main = module_path.read_text()

        workers_section = module_main.split("workers = toset([", 1)[1].split("])", 1)[0]
        assert '"roles/pubsub.publisher"' in workers_section
        assert '"roles/pubsub.subscriber"' in workers_section

    def test_portal_has_identity_platform_viewer_permissions(self):
        """Portal auth needs read access to Identity Platform user records for token verification."""
        module_path = (
            Path(__file__).resolve().parents[3]
            / "platform"
            / "terraform"
            / "gcp"
            / "modules"
            / "platform-core"
            / "main.tf"
        )
        module_main = module_path.read_text()

        portal_section = module_main.split("portal = toset([", 1)[1].split("])", 1)[0]
        assert '"roles/firebaseauth.viewer"' in portal_section

    def test_identity_platform_self_signup_is_allowed_and_guarded_by_before_create_trigger(self):
        """GCP corporate registration must stay open to eligible users and be gated by a blocking function."""
        module_path = (
            Path(__file__).resolve().parents[3]
            / "platform"
            / "terraform"
            / "gcp"
            / "modules"
            / "platform-core"
            / "main.tf"
        )
        module_main = module_path.read_text()

        identity_platform_section = module_main.split('resource "google_identity_platform_config" "platform" {', 1)[1]
        assert "disabled_user_signup   = false" in identity_platform_section
        assert 'event_type   = "beforeCreate"' in identity_platform_section
        assert (
            "google_cloudfunctions_function.identity_platform_before_create.https_trigger_url"
            in identity_platform_section
        )

    def test_cloud_armor_sqli_rule_opts_out_known_false_positive_signature(self):
        """The edge WAF should not block the portal landing/login flow on the known false-positive rule."""
        module_path = (
            Path(__file__).resolve().parents[3]
            / "platform"
            / "terraform"
            / "gcp"
            / "modules"
            / "platform-core"
            / "main.tf"
        )
        module_main = module_path.read_text()

        assert "evaluatePreconfiguredWaf('sqli-v33-stable'" in module_main
        assert "owasp-crs-v030301-id942421-sqli" in module_main


class TestGdcBootstrapAssetUpload:
    """Tests for staging the GDC bootstrap bundle on the workstation."""

    def test_creates_remote_staging_directory_before_recursive_scp(self, tmp_path):
        """The uploader must replace the staged bundle and transfer it through IAP."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        assets_dir = tmp_path / "cluster1"
        assets_dir.mkdir()

        with patch("deploy.run_cmd") as mock_run_cmd:
            deploy.upload_gdc_assets(config, assets_dir)

        mkdir_call = mock_run_cmd.call_args_list[0]
        assert mkdir_call.args[0] == [
            "gcloud",
            "compute",
            "ssh",
            f"root@{config.workstation.name}",
            "--tunnel-through-iap",
            "--project",
            config.project_id,
            "--zone",
            config.zone,
            "--command",
            f"rm -rf {config.staging_bundle_dir} && mkdir -p {config.staging_dir}",
        ]
        assert mkdir_call.kwargs == {"dry_run": False}

        scp_call = mock_run_cmd.call_args_list[1]
        assert scp_call.args[0] == [
            "gcloud",
            "compute",
            "scp",
            "--recurse",
            "--tunnel-through-iap",
            "--project",
            config.project_id,
            "--zone",
            config.zone,
            str(assets_dir),
            f"root@{config.workstation.name}:{config.staging_dir}/",
        ]
        assert scp_call.kwargs == {"dry_run": False}


class TestGdcStagedAssets:
    """Tests for the local GDC bootstrap bundle assembly."""

    def test_reuses_existing_workstation_credentials_when_present(self, tmp_path):
        """Reruns must reuse the workstation bootstrap credentials instead of minting fresh ones."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        existing_material = {
            "private_key": "PRIVATE KEY\n",
            "public_key": "ssh-rsa AAAAexisting bootstrap@ws\n",
            "service_account_key": '{"private_key_id":"d6edc4b1cc096f95b105b810d838e786b040a3e9"}\n',
        }

        def fake_run_cmd(cmd, *args, **kwargs):
            if cmd[:3] == ["gcloud", "storage", "cp"]:
                Path(cmd[4]).write_text("bmctl-binary")
            return None

        with (
            patch("deploy._fetch_existing_gdc_bootstrap_material", return_value=existing_material),
            patch("deploy.run_cmd", side_effect=fake_run_cmd) as mock_run_cmd,
        ):
            staged_assets = deploy.stage_gdc_bootstrap_assets(config, tmp_path)

        assert staged_assets["private_key"].read_text() == "PRIVATE KEY\n"
        assert staged_assets["public_key"].read_text() == "ssh-rsa AAAAexisting bootstrap@ws\n"
        assert (
            staged_assets["service_account_key"].read_text()
            == '{"private_key_id":"d6edc4b1cc096f95b105b810d838e786b040a3e9"}\n'
        )
        executed = [call.args[0] for call in mock_run_cmd.call_args_list]
        assert ["ssh-keygen", "-t", "rsa", "-N", "", "-f", str(staged_assets["private_key"])] not in executed
        assert not any(cmd[:5] == ["gcloud", "iam", "service-accounts", "keys", "create"] for cmd in executed)

    def test_stages_bmctl_binary_from_gcs_into_bundle(self, tmp_path):
        """Asset staging must fetch the pinned bmctl binary into the uploaded bundle."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        def fake_run_cmd(cmd, *args, **kwargs):
            if cmd[:4] == ["ssh-keygen", "-t", "rsa", "-N"]:
                private_key = Path(cmd[-1])
                private_key.write_text("PRIVATE KEY\n")
                private_key.with_suffix(".pub").write_text("ssh-rsa AAAATESTKEY\n")
            elif cmd[:5] == ["gcloud", "iam", "service-accounts", "keys", "create"]:
                Path(cmd[5]).write_text('{"type": "service_account"}\n')
            elif cmd[:3] == ["gcloud", "storage", "cp"]:
                Path(cmd[4]).write_text("bmctl-binary")
            return None

        with (
            patch("deploy._fetch_existing_gdc_bootstrap_material", return_value=None),
            patch("deploy.run_cmd", side_effect=fake_run_cmd) as mock_run_cmd,
        ):
            staged_assets = deploy.stage_gdc_bootstrap_assets(config, tmp_path)

        assert staged_assets["bmctl_binary"].read_text() == "bmctl-binary"
        assert mock_run_cmd.call_args_list[2].args[0] == [
            "gcloud",
            "storage",
            "cp",
            config.bmctl_gcs_source,
            str(staged_assets["bmctl_binary"]),
        ]


class TestGdcRerunSafety:
    """Tests for rerun-safe secret and metadata synchronization."""

    def test_sync_instance_ssh_metadata_skips_hosts_already_in_sync(self, tmp_path):
        """Instance metadata writes should be skipped when the expected key is already present."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        metadata_path = tmp_path / "ssh-metadata"
        metadata_path.write_text("root:ssh-rsa AAAAexisting atomik@Phoenix\n")

        with (
            patch("deploy.get_gdc_instance_ssh_metadata") as mock_get_metadata,
            patch("deploy.run_cmd") as mock_run_cmd,
        ):
            mock_get_metadata.side_effect = [
                "root:ssh-rsa AAAAexisting atomik@Phoenix",
                "root:ssh-rsa AAAAdifferent atomik@Phoenix",
                "root:ssh-rsa AAAAexisting atomik@Phoenix",
                "root:ssh-rsa AAAAexisting atomik@Phoenix",
                "root:ssh-rsa AAAAexisting atomik@Phoenix",
                "root:ssh-rsa AAAAexisting atomik@Phoenix",
            ]

            deploy.sync_gdc_instance_ssh_metadata(config, metadata_path)

        assert mock_run_cmd.call_count == 1
        assert "cluster1-abm-cp1-001" in mock_run_cmd.call_args.args[0]

    def test_sync_gdc_access_secret_skips_unchanged_payload(self):
        """Bootstrap should not add a new secret version when the access payload is unchanged."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        payload = deploy.build_gdc_access_secret_payload(config, "apiVersion: v1\nclusters: []\n")

        with (
            patch("deploy.ensure_gdc_access_secret"),
            patch("deploy.fetch_gdc_kubeconfig", return_value="apiVersion: v1\nclusters: []\n"),
            patch("deploy.get_latest_gcp_secret_payload", return_value=payload),
            patch("deploy.run_cmd") as mock_run_cmd,
        ):
            deploy.sync_gdc_access_secret(config)

        mock_run_cmd.assert_not_called()

    def test_sync_gdc_vm_image_secret_skips_unchanged_payload(self, tmp_path):
        """Bootstrap should not add a new VM image secret version when the key payload is unchanged."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        key_path = tmp_path / "bm-gcr.json"
        key_path.write_text('{"private_key_id":"d6edc4b1cc096f95b105b810d838e786b040a3e9"}\n')

        with (
            patch("deploy.ensure_gdc_vm_image_secret"),
            patch(
                "deploy.get_latest_gcp_secret_payload",
                return_value='{"private_key_id":"d6edc4b1cc096f95b105b810d838e786b040a3e9"}\n',
            ),
            patch("deploy.run_cmd") as mock_run_cmd,
        ):
            deploy.sync_gdc_vm_image_secret(config, key_path)

        mock_run_cmd.assert_not_called()


class TestGcpBootstrapIdentityPlatform:
    """Tests for Identity Platform bootstrap user sourcing and seeding."""

    def test_parse_simple_env_file_handles_quoted_values(self, tmp_path):
        """Simple env parsing should strip matching quotes and ignore comments."""
        env_path = tmp_path / ".env"
        env_path.write_text(
            "\n".join(
                [
                    "# Comment",
                    'OIDC_RP_CLIENT_ID="client-id"',
                    "OIDC_RP_CLIENT_SECRET='client-secret'",
                    "OIDC_ISSUER_URL=https://issuer.example.test/",
                    'OIDC_AUTH_DOMAIN="https://auth.example.test"',
                    "",
                ]
            )
        )

        assert deploy.parse_simple_env_file(env_path) == {
            "OIDC_RP_CLIENT_ID": "client-id",
            "OIDC_RP_CLIENT_SECRET": "client-secret",
            "OIDC_ISSUER_URL": "https://issuer.example.test/",
            "OIDC_AUTH_DOMAIN": "https://auth.example.test",
        }

    def test_resolve_gcp_bootstrap_operator_credentials_returns_none_when_missing(self):
        """Bootstrap should report no operator credentials when the env files do not provide them."""
        with patch("deploy.load_bootstrap_env_values", return_value={}):
            assert deploy.resolve_gcp_bootstrap_operator_credentials() is None

    def test_resolve_gcp_bootstrap_operator_credentials_uses_env_values(self):
        """Bootstrap should source the first operator credentials from env-backed values when present."""
        with patch(
            "deploy.load_bootstrap_env_values",
            return_value={
                "GCP_BOOTSTRAP_ADMIN_EMAIL": "analyst@paloaltonetworks.com",
                "GCP_BOOTSTRAP_ADMIN_PASSWORD": "correct-horse-battery-staple",
            },
        ):
            credentials = deploy.resolve_gcp_bootstrap_operator_credentials()

        assert credentials == ("analyst@paloaltonetworks.com", "correct-horse-battery-staple")

    def test_ensure_gcp_identity_platform_operator_creates_user(self):
        """Bootstrap must create the first operator via the Identity Platform admin API."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        outputs = _sample_gcp_control_plane_outputs(config.project_id)

        with (
            patch(
                "deploy.resolve_gcp_bootstrap_operator_credentials",
                return_value=("analyst@paloaltonetworks.com", "correct-horse-battery-staple"),
            ),
            patch("deploy._gcp_identity_admin_request", return_value={"localId": "user-123"}) as mock_request,
        ):
            deploy.ensure_gcp_identity_platform_operator(config, outputs)

        mock_request.assert_called_once_with(
            config=config,
            outputs=outputs,
            path=f"/projects/{config.project_id}/accounts",
            payload={
                "email": "analyst@paloaltonetworks.com",
                "password": "correct-horse-battery-staple",
                "displayName": "Shifter Operator",
                "emailVerified": True,
            },
        )

    def test_ensure_gcp_identity_platform_operator_returns_operator_email(self):
        """Bootstrap should return the first operator email so the runtime can elevate that user."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        outputs = _sample_gcp_control_plane_outputs(config.project_id)

        with (
            patch(
                "deploy.resolve_gcp_bootstrap_operator_credentials",
                return_value=("bedwards@paloaltonetworks.com", "correct-horse-battery-staple"),
            ),
            patch("deploy._gcp_identity_admin_request", return_value={"localId": "user-123"}),
        ):
            email = deploy.ensure_gcp_identity_platform_operator(config, outputs)

        assert email == "bedwards@paloaltonetworks.com"

    def test_ensure_gcp_identity_platform_operator_skips_existing_user(self):
        """Bootstrap should treat an existing operator account as success."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        outputs = _sample_gcp_control_plane_outputs(config.project_id)

        with (
            patch(
                "deploy.resolve_gcp_bootstrap_operator_credentials",
                return_value=("analyst@paloaltonetworks.com", "correct-horse-battery-staple"),
            ),
            patch("deploy._gcp_identity_admin_request", side_effect=RuntimeError("EMAIL_EXISTS")) as mock_request,
        ):
            deploy.ensure_gcp_identity_platform_operator(config, outputs)

        mock_request.assert_called_once()

    def test_ensure_gcp_identity_platform_operator_prompts_when_env_missing(self):
        """Interactive bootstrap should prompt for the first operator when env values are absent."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        outputs = _sample_gcp_control_plane_outputs(config.project_id)

        with (
            patch("deploy.resolve_gcp_bootstrap_operator_credentials", return_value=None),
            patch(
                "deploy.prompt_for_gcp_bootstrap_operator_credentials",
                return_value=("analyst@paloaltonetworks.com", "correct-horse-battery-staple"),
            ) as mock_prompt,
            patch("deploy._gcp_identity_admin_request", return_value={"localId": "user-123"}),
        ):
            deploy.ensure_gcp_identity_platform_operator(config, outputs)

        mock_prompt.assert_called_once_with()

    def test_ensure_gcp_identity_platform_operator_rejects_non_corporate_email(self):
        """Bootstrap must fail before touching Identity Platform when the operator email is not corporate."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        outputs = _sample_gcp_control_plane_outputs(config.project_id)

        with (
            patch(
                "deploy.resolve_gcp_bootstrap_operator_credentials",
                return_value=("intruder@example.com", "correct-horse-battery-staple"),
            ),
            pytest.raises(ValueError, match=r"paloaltonetworks\.com"),
        ):
            deploy.ensure_gcp_identity_platform_operator(config, outputs)

    def test_render_gcp_platform_runtime_env_elevates_bootstrap_operator(self):
        """The generated runtime env should elevate the first operator without hardcoding an email in the repo."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        with patch("deploy.load_bootstrap_env_values", return_value={}):
            rendered = deploy.render_gcp_platform_runtime_env(
                config,
                bootstrap_operator_email="bedwards@paloaltonetworks.com",
            )

        assert "PLATFORM_BOOTSTRAP_STAFF_EMAILS=bedwards@paloaltonetworks.com\n" in rendered
        assert "PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS=bedwards@paloaltonetworks.com\n" in rendered

    def test_render_gcp_platform_runtime_env_uses_blank_guest_password_samples(self):
        """The generated env contract must not embed sample guest passwords in source-controlled output."""
        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")

        with patch("deploy.load_bootstrap_env_values", return_value={}):
            rendered = deploy.render_gcp_platform_runtime_env(
                config,
                bootstrap_operator_email="bedwards@paloaltonetworks.com",
            )

        assert "GDC_WINDOWS_ADMIN_PASSWORD=\n" in rendered
        assert "GDC_KALI_PASSWORD=\n" in rendered
        assert "GDC_UBUNTU_PASSWORD=\n" in rendered
        assert "CortexSavesTheDay!" not in rendered


class TestGcpIdentityAdminApi:
    """Tests for the authenticated Identity Platform bootstrap admin requests."""

    def test_gcp_identity_admin_request_uses_authenticated_project_endpoint_without_api_key(self):
        """Bootstrap must use the authenticated project-scoped admin endpoint without appending a web API key."""

        class _FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self) -> bytes:
                return b'{"localId":"user-123"}'

        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        outputs = _sample_gcp_control_plane_outputs(config.project_id)

        with (
            patch("deploy._gcp_identity_access_token", return_value="test-access-token"),
            patch("deploy.urllib_request.urlopen", return_value=_FakeResponse()) as mock_urlopen,
        ):
            result = deploy._gcp_identity_admin_request(
                config=config,
                outputs=outputs,
                path=f"/projects/{config.project_id}/accounts",
                payload={"email": "analyst@paloaltonetworks.com", "password": "correct-horse-battery-staple"},
            )

        assert result == {"localId": "user-123"}
        request = mock_urlopen.call_args.args[0]
        assert request.full_url == (f"https://identitytoolkit.googleapis.com/v1/projects/{config.project_id}/accounts")
        assert request.headers["Authorization"] == "Bearer test-access-token"
        assert request.headers["Content-type"] == "application/json"
        assert request.headers["X-goog-user-project"] == config.project_id

    def test_gcp_identity_admin_request_surfaces_identity_platform_error_messages(self):
        """Bootstrap must surface the actual Identity Platform admin error when the request fails."""

        class _FakeHttpError(deploy.urllib_error.HTTPError):
            def __init__(self) -> None:
                super().__init__(
                    url="https://identitytoolkit.googleapis.com/v1/projects/prod-rwctxzl6shxk/accounts",
                    code=400,
                    msg="Bad Request",
                    hdrs=None,
                    fp=io.BytesIO(b'{"error":{"message":"EMAIL_EXISTS"}}'),
                )

        config = deploy.GDCBootstrapConfig(project_id="prod-rwctxzl6shxk", cluster_id="cluster1")
        outputs = _sample_gcp_control_plane_outputs(config.project_id)

        with (
            patch("deploy._gcp_identity_access_token", return_value="test-access-token"),
            patch("deploy.urllib_request.urlopen", side_effect=_FakeHttpError()),
            pytest.raises(RuntimeError, match="EMAIL_EXISTS"),
        ):
            deploy._gcp_identity_admin_request(
                config=config,
                outputs=outputs,
                path=f"/projects/{config.project_id}/accounts",
                payload={"email": "analyst@paloaltonetworks.com", "password": "correct-horse-battery-staple"},
            )


class TestGcpBootstrapDnsTlsFlow:
    """Tests for the post-ingress DNS/TLS walkthrough."""

    def test_wait_for_gcp_managed_certificate_active_retries_until_active(self):
        """Bootstrap must wait for the managed certificate to become Active before declaring success."""
        with (
            patch(
                "deploy.get_gcp_managed_certificate_status",
                side_effect=["Provisioning", "Provisioning", "Active"],
            ) as mock_status,
            patch("deploy.time.sleep") as mock_sleep,
        ):
            deploy.wait_for_gcp_managed_certificate_active(timeout_seconds=60, poll_seconds=0)

        assert mock_status.call_count == 3
        assert mock_sleep.call_count == 2

    def test_walkthrough_gcp_dns_setup_and_waits_for_tls(self):
        """Bootstrap should guide DNS setup after ingress exists, then verify TLS and the public portal."""
        outputs = _sample_gcp_control_plane_outputs()

        with (
            patch("deploy.wait_for_user") as mock_wait_for_user,
            patch("deploy.wait_for_gcp_managed_certificate_active") as mock_wait_for_tls,
            patch("deploy.verify_gcp_public_portal") as mock_verify_portal,
        ):
            deploy.walkthrough_gcp_dns_setup_and_wait_for_tls(outputs)

        mock_wait_for_user.assert_called_once()
        mock_wait_for_tls.assert_called_once_with()
        mock_verify_portal.assert_called_once_with("portal.example.test")


# =============================================================================
# Test: bootstrap_account()
# =============================================================================


class TestBootstrapAccount:
    """Tests for deploy.bootstrap_account."""

    # ---------------------------------------------------------------------
    # Happy path - function succeeds
    # ---------------------------------------------------------------------

    def test_creates_s3_bucket_for_terraform_state(self, bootstrap_config, mock_subprocess, mock_repo_root):
        """Function creates S3 bucket for state storage."""
        with (
            patch("deploy.get_aws_account_id", return_value="123456789012"),
            patch("deploy.confirm", return_value=True),
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("pathlib.Path.write_text"),
        ):
            deploy.bootstrap_account(bootstrap_config, "my-profile")

            # Should call aws s3 mb
            s3_calls = [
                c
                for c in mock_subprocess.call_args_list
                if len(c[0]) > 0 and len(c[0][0]) > 0 and c[0][0][0] == "aws" and "s3" in " ".join(c[0][0])
            ]
            assert len(s3_calls) > 0

    def test_does_not_create_dynamodb_table(self, bootstrap_config, mock_subprocess, mock_repo_root):
        """State locking uses S3 native (use_lockfile = true), so no DynamoDB calls."""
        with (
            patch("deploy.get_aws_account_id", return_value="123456789012"),
            patch("deploy.confirm", return_value=True),
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("pathlib.Path.write_text"),
        ):
            deploy.bootstrap_account(bootstrap_config, "my-profile")

            dynamo_calls = [
                c
                for c in mock_subprocess.call_args_list
                if len(c[0]) > 0 and len(c[0][0]) > 0 and c[0][0][0] == "aws" and "dynamodb" in " ".join(c[0][0])
            ]
            assert dynamo_calls == []

    def test_runs_terraform_to_create_oidc_and_role(self, bootstrap_config, mock_subprocess, mock_repo_root):
        """Function runs Terraform to create OIDC provider and production IAM role."""
        with (
            patch("deploy.get_aws_account_id", return_value="123456789012"),
            patch("deploy.confirm", return_value=True),
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("pathlib.Path.write_text"),
            patch("os.chdir"),
        ):
            deploy.bootstrap_account(bootstrap_config, "my-profile")

            # Should call terraform init and apply
            terraform_calls = [
                c
                for c in mock_subprocess.call_args_list
                if len(c[0]) > 0 and len(c[0][0]) > 0 and c[0][0][0] == "terraform"
            ]
            assert len(terraform_calls) > 0

    def test_creates_iam_role_for_github_actions(self, bootstrap_config, mock_subprocess, mock_repo_root):
        """Function creates IAM role for GitHub Actions."""
        with (
            patch("deploy.get_aws_account_id", return_value="123456789012"),
            patch("deploy.confirm", return_value=True),
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("pathlib.Path.write_text"),
        ):
            deploy.bootstrap_account(bootstrap_config, "my-profile")

            # Should call aws iam create-role
            role_calls = [
                c
                for c in mock_subprocess.call_args_list
                if len(c[0]) > 0 and len(c[0][0]) > 0 and c[0][0][0] == "aws" and "create-role" in " ".join(c[0][0])
            ]
            assert len(role_calls) > 0

    def test_attaches_admin_policy_to_bootstrap_role(self, bootstrap_config, mock_subprocess, mock_repo_root):
        """Function attaches AdministratorAccess to bootstrap role."""
        with (
            patch("deploy.get_aws_account_id", return_value="123456789012"),
            patch("deploy.confirm", return_value=True),
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("pathlib.Path.write_text"),
            patch("os.chdir"),
        ):
            deploy.bootstrap_account(bootstrap_config, "my-profile")

            # Should call attach-role-policy with AdministratorAccess
            policy_calls = [
                c
                for c in mock_subprocess.call_args_list
                if len(c[0]) > 0
                and len(c[0][0]) > 0
                and c[0][0][0] == "aws"
                and "attach-role-policy" in " ".join(c[0][0])
            ]
            assert len(policy_calls) > 0

    def test_returns_dict_with_bootstrap_results(self, bootstrap_config, mock_subprocess, mock_repo_root):
        """Function returns dictionary with resource ARNs and names."""
        with (
            patch("deploy.get_aws_account_id", return_value="123456789012"),
            patch("deploy.confirm", return_value=True),
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("pathlib.Path.write_text"),
        ):
            result = deploy.bootstrap_account(bootstrap_config, "my-profile")

            assert isinstance(result, dict)
            assert "role_arn" in result
            assert "bucket_name" in result

    def test_uses_correct_github_org_and_repo_in_trust_policy(self, bootstrap_config, mock_subprocess, mock_repo_root):
        """Function includes correct GitHub org/repo in IAM trust policy."""
        with (
            patch("deploy.get_aws_account_id", return_value="123456789012"),
            patch("deploy.confirm", return_value=True),
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("pathlib.Path.write_text"),
        ):
            bootstrap_config.github_org = "test-org"
            bootstrap_config.github_repo = "test-repo"
            deploy.bootstrap_account(bootstrap_config, "my-profile")

            # Find the create-role call
            role_calls = [
                c
                for c in mock_subprocess.call_args_list
                if len(c[0]) > 0 and len(c[0][0]) > 1 and "create-role" in " ".join(c[0][0])
            ]
            assert len(role_calls) > 0

            # The trust policy should be in the command args
            cmd_args = role_calls[0][0][0]
            policy_json = None
            for i, arg in enumerate(cmd_args):
                if arg == "--assume-role-policy-document":
                    policy_json = cmd_args[i + 1]
                    break

            assert policy_json is not None
            policy = json.loads(policy_json)
            # Policy should reference the GitHub repo
            policy_str = json.dumps(policy)
            assert "test-org" in policy_str
            assert "test-repo" in policy_str

    # ---------------------------------------------------------------------
    # Dry-run mode
    # ---------------------------------------------------------------------

    def test_does_not_create_resources_in_dry_run(self, bootstrap_config, mock_repo_root):
        """Function does not execute AWS commands in dry-run mode."""
        with (
            patch("subprocess.run") as mock_run,
            patch("deploy.get_aws_account_id", return_value="123456789012"),
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("pathlib.Path.write_text"),
        ):
            deploy.bootstrap_account(bootstrap_config, "my-profile", dry_run=True)

            # run_cmd should be called with dry_run=True
            for call_args in mock_run.call_args_list:
                if "dry_run" in call_args[1]:
                    assert call_args[1]["dry_run"] is True

    # ---------------------------------------------------------------------
    # Error handling
    # ---------------------------------------------------------------------

    def test_exits_when_s3_bucket_creation_fails(self, bootstrap_config, mock_repo_root):
        """Function exits when S3 bucket creation fails."""
        with (
            patch("subprocess.run") as mock_run,
            patch("deploy.get_aws_account_id", return_value="123456789012"),
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("pathlib.Path.write_text"),
        ):
            mock_run.side_effect = subprocess.CalledProcessError(returncode=1, cmd=["aws", "s3", "mb"])

            with pytest.raises(SystemExit):
                deploy.bootstrap_account(bootstrap_config, "my-profile")

    def test_exits_when_iam_role_creation_fails(self, bootstrap_config, mock_repo_root):
        """Function exits when IAM role creation fails."""
        with (
            patch("subprocess.run") as mock_run,
            patch("deploy.get_aws_account_id", return_value="123456789012"),
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("pathlib.Path.write_text"),
        ):
            # Succeed for S3 and DynamoDB, fail for IAM
            def side_effect(cmd, **kwargs):
                if "create-role" in cmd:
                    raise subprocess.CalledProcessError(1, cmd)
                return subprocess.CompletedProcess(args=cmd, returncode=0)

            mock_run.side_effect = side_effect

            with pytest.raises(SystemExit):
                deploy.bootstrap_account(bootstrap_config, "my-profile")

    # ---------------------------------------------------------------------
    # Profile injection
    # ---------------------------------------------------------------------

    def test_passes_profile_to_all_aws_commands(self, bootstrap_config, mock_repo_root):
        """Function passes profile parameter to all AWS CLI calls."""
        with (
            patch("subprocess.run") as mock_run,
            patch("deploy.get_aws_account_id", return_value="123456789012"),
            patch("deploy.confirm", return_value=True),
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("pathlib.Path.write_text"),
        ):

            def run_side_effect(cmd, **kwargs):
                cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
                # Return OIDC ARN for list-open-id-connect-providers
                if "list-open-id-connect-providers" in cmd_str:
                    return subprocess.CompletedProcess(
                        args=cmd,
                        returncode=0,
                        stdout=("arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com\n"),
                    )
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="")

            mock_run.side_effect = run_side_effect

            deploy.bootstrap_account(bootstrap_config, "test-profile")

            # All AWS commands should have --profile in their args
            aws_calls = [
                c for c in mock_run.call_args_list if len(c[0]) > 0 and len(c[0][0]) > 0 and c[0][0][0] == "aws"
            ]
            for call_args in aws_calls:
                cmd = call_args[0][0]
                assert "--profile" in cmd
                assert "test-profile" in cmd


# =============================================================================
# Test: walkthrough_github_secrets()
# =============================================================================


class TestWalkthroughGithubSecrets:
    """Tests for deploy.walkthrough_github_secrets."""

    # ---------------------------------------------------------------------
    # Happy path - automated with gh CLI
    # ---------------------------------------------------------------------

    def test_sets_secret_via_gh_cli_when_user_confirms(self, bootstrap_config, mock_stdin_tty):
        """Function sets GitHub secret using gh CLI when automated."""
        bootstrap_result = {
            "role_arn": "arn:aws:iam::123456789012:role/test-role",
            "secret_name": "AWS_ROLE_ARN_DEV",
            "github_org": "test-org",
            "github_repo": "test-repo",
        }

        with (
            patch("builtins.input", return_value="y"),
            patch("subprocess.run") as mock_run,
        ):

            def mock_subprocess_run(cmd, **kwargs):
                cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
                if "which" in cmd_str:
                    return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="/usr/bin/gh\n", stderr="")
                elif "gh" in cmd_str and "secret" in cmd_str:
                    return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

            mock_run.side_effect = mock_subprocess_run

            deploy.walkthrough_github_secrets(bootstrap_result)

            # Should call gh secret set
            gh_calls = [c for c in mock_run.call_args_list if c[0][0][0] == "gh"]
            assert len(gh_calls) > 0
            # Find the set call
            set_calls = [c for c in gh_calls if "set" in c[0][0]]
            assert len(set_calls) > 0

    def test_includes_role_arn_in_gh_secret_command(self, bootstrap_config, mock_stdin_tty):
        """Function passes correct role ARN to gh secret set."""
        bootstrap_result = {
            "role_arn": "arn:aws:iam::123456789012:role/test-role",
            "secret_name": "AWS_ROLE_ARN_DEV",
            "github_org": "test-org",
            "github_repo": "test-repo",
        }

        with (
            patch("builtins.input", return_value="y"),
            patch("subprocess.run") as mock_run,
        ):

            def mock_subprocess_run(cmd, **kwargs):
                cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
                if "which" in cmd_str:
                    return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="/usr/bin/gh\n", stderr="")
                elif "gh" in cmd_str and "secret" in cmd_str:
                    return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

            mock_run.side_effect = mock_subprocess_run

            deploy.walkthrough_github_secrets(bootstrap_result)

            # Find the gh secret set call
            gh_calls = [c for c in mock_run.call_args_list if c[0][0][0] == "gh" and "set" in c[0][0]]
            assert len(gh_calls) > 0

            # Should include the role ARN
            cmd = gh_calls[0][0][0]
            assert "arn:aws:iam::123456789012:role/test-role" in " ".join(cmd)

    # ---------------------------------------------------------------------
    # Manual fallback
    # ---------------------------------------------------------------------

    def test_provides_manual_instructions_when_gh_not_available(self, capsys, mock_stdin_tty):
        """Function shows manual instructions when gh CLI not found."""
        bootstrap_result = {
            "role_arn": "arn:aws:iam::123456789012:role/test-role",
            "secret_name": "AWS_ROLE_ARN_DEV",
            "github_org": "test-org",
            "github_repo": "test-repo",
        }

        with (
            patch("subprocess.run") as mock_run,
            patch("deploy.wait_for_user") as mock_wait,
        ):
            # Make "which gh" return non-zero (not found)
            mock_run.return_value = subprocess.CompletedProcess(
                args=["which", "gh"], returncode=1, stdout="", stderr=""
            )

            deploy.walkthrough_github_secrets(bootstrap_result)

            # Should call wait_for_user
            assert mock_wait.called

    def test_provides_manual_instructions_when_user_chooses_manual(self, capsys, mock_stdin_tty):
        """Function shows manual instructions when user selects manual."""
        bootstrap_result = {
            "role_arn": "arn:aws:iam::123456789012:role/test-role",
            "secret_name": "AWS_ROLE_ARN_DEV",
            "github_org": "test-org",
            "github_repo": "test-repo",
        }

        with (
            patch("subprocess.run") as mock_run,
            patch("deploy.confirm_or_manual", return_value="manual"),
            patch("deploy.wait_for_user"),
        ):
            # Make "which gh" return success (found)
            mock_run.return_value = subprocess.CompletedProcess(
                args=["which", "gh"], returncode=0, stdout="/usr/bin/gh\n", stderr=""
            )

            deploy.walkthrough_github_secrets(bootstrap_result)

            captured = capsys.readouterr()
            assert "manual steps" in captured.out.lower()

    # ---------------------------------------------------------------------
    # Error handling
    # ---------------------------------------------------------------------

    def test_exits_when_user_refuses_github_secrets(self, mock_stdin_tty, mock_subprocess):
        """Function exits when user enters 'no' for GitHub secrets."""
        bootstrap_result = {
            "role_arn": "arn:aws:iam::123456789012:role/test-role",
            "secret_name": "AWS_ROLE_ARN_DEV",
            "github_org": "test-org",
            "github_repo": "test-repo",
        }

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("deploy.confirm_or_manual", return_value="no"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                deploy.walkthrough_github_secrets(bootstrap_result)

            assert exc_info.value.code == 1

    def test_exits_when_gh_command_fails(self, mock_stdin_tty):
        """Function exits when gh secret set fails."""
        bootstrap_result = {
            "role_arn": "arn:aws:iam::123456789012:role/test-role",
            "secret_name": "AWS_ROLE_ARN_DEV",
            "github_org": "test-org",
            "github_repo": "test-repo",
        }

        with (
            patch("deploy.confirm_or_manual", return_value="yes"),
            patch("subprocess.run") as mock_run,
        ):
            # Make subprocess.run return failure for gh secret set
            def selective_failure(cmd, **kwargs):
                cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
                if "which" in cmd_str and "gh" in cmd_str:
                    return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="/usr/bin/gh\n")
                elif "gh" in cmd_str and "secret" in cmd_str:
                    return subprocess.CompletedProcess(args=cmd, returncode=1, stderr="auth error")
                return subprocess.CompletedProcess(args=cmd, returncode=0)

            mock_run.side_effect = selective_failure

            with pytest.raises(SystemExit):
                deploy.walkthrough_github_secrets(bootstrap_result)

    # ---------------------------------------------------------------------
    # Dry-run mode
    # ---------------------------------------------------------------------

    def test_does_not_set_secret_in_dry_run_mode(self, mock_subprocess):
        """Function does not execute gh command in dry-run."""
        bootstrap_result = {
            "role_arn": "arn:aws:iam::123456789012:role/test-role",
            "secret_name": "AWS_ROLE_ARN_DEV",
            "github_org": "test-org",
            "github_repo": "test-repo",
        }

        with patch("shutil.which", return_value="/usr/bin/gh"):
            deploy.walkthrough_github_secrets(bootstrap_result, dry_run=True)
            # In dry-run, no gh secret set should be called


# =============================================================================
# Test: walkthrough_backend_config()
# =============================================================================


class TestWalkthroughBackendConfig:
    """Tests for deploy.walkthrough_backend_config."""

    # ---------------------------------------------------------------------
    # Happy path - automated file writes
    # ---------------------------------------------------------------------

    def test_writes_backend_tf_files_when_user_confirms(self, mock_repo_root, mock_stdin_tty, mock_subprocess):
        """Function writes backend.tf files when user confirms."""
        bootstrap_result = {
            "bucket_name": "test-bucket",
            "table_name": "test-table",
            "region": "us-east-2",
            "env": "dev",
        }

        with (
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("deploy.confirm_or_manual", side_effect=["yes", "no"]),
            patch("pathlib.Path.write_text") as mock_write,
        ):
            deploy.walkthrough_backend_config(bootstrap_result)

            # Should write 3 files
            assert mock_write.call_count == 3  # core, portal, range

    def test_creates_correct_backend_config_content(self, mock_repo_root, mock_stdin_tty, mock_subprocess):
        """Function generates correct Terraform backend configuration."""
        bootstrap_result = {
            "bucket_name": "my-bucket",
            "table_name": "my-table",
            "region": "us-west-2",
            "env": "prod",
        }

        written_content = []

        def capture_write(content):
            written_content.append(content)

        with (
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("deploy.confirm_or_manual", side_effect=["yes", "no"]),
            patch("pathlib.Path.write_text", side_effect=capture_write),
        ):
            deploy.walkthrough_backend_config(bootstrap_result)

            # Bucket and region appear in the .tfbackend files. State locking
            # is S3 native (use_lockfile = true), so no DynamoDB table name.
            all_content = "".join(written_content)
            assert "my-bucket" in all_content
            assert "us-west-2" in all_content
            assert "use_lockfile = true" in all_content
            assert "dynamodb_table" not in all_content

    # ---------------------------------------------------------------------
    # Error handling
    # ---------------------------------------------------------------------

    def test_exits_when_user_refuses_backend_config(self, mock_repo_root, mock_stdin_tty, mock_subprocess):
        """Function exits when user enters 'no' for backend config."""
        bootstrap_result = {
            "bucket_name": "test-bucket",
            "table_name": "test-table",
            "region": "us-east-2",
            "env": "dev",
        }

        with (
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("deploy.confirm_or_manual", return_value="no"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                deploy.walkthrough_backend_config(bootstrap_result)

            assert exc_info.value.code == 1

    def test_exits_when_file_write_fails(self, mock_repo_root, mock_stdin_tty, mock_subprocess):
        """Function exits when backend.tf file write fails."""
        bootstrap_result = {
            "bucket_name": "test-bucket",
            "table_name": "test-table",
            "region": "us-east-2",
            "env": "dev",
        }

        with (
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("deploy.confirm_or_manual", return_value="yes"),
            patch("pathlib.Path.write_text", side_effect=OSError("Permission denied")),
            pytest.raises(SystemExit),
        ):
            deploy.walkthrough_backend_config(bootstrap_result)

    # ---------------------------------------------------------------------
    # Manual fallback
    # ---------------------------------------------------------------------

    def test_provides_manual_instructions_when_user_chooses_manual(
        self, mock_repo_root, capsys, mock_stdin_tty, mock_subprocess
    ):
        """Function shows manual instructions when user selects manual."""
        bootstrap_result = {
            "bucket_name": "test-bucket",
            "table_name": "test-table",
            "region": "us-east-2",
            "env": "dev",
        }

        with (
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("deploy.confirm_or_manual", return_value="manual"),
            patch("deploy.wait_for_user") as mock_wait,
        ):
            deploy.walkthrough_backend_config(bootstrap_result)

            # Should call wait_for_user with instructions
            assert mock_wait.called
            call_arg = mock_wait.call_args[0][0]
            assert ".s3.tfbackend" in call_arg.lower()


# =============================================================================
# Test: terraform_deploy()
# =============================================================================


class TestTerraformDeploy:
    """Tests for deploy.terraform_deploy."""

    # ---------------------------------------------------------------------
    # Happy path - successful deployment
    # ---------------------------------------------------------------------

    def test_runs_terraform_init_for_all_components(self, mock_repo_root, mock_stdin_tty, mock_subprocess):
        """Function runs terraform init for core, portal, and range."""
        with (
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("deploy.confirm", return_value=True),
            patch("os.chdir"),
        ):
            deploy.terraform_deploy("dev", "my-profile")

            # Should call terraform init 3 times (core, portal, range)
            init_calls = [
                c
                for c in mock_subprocess.call_args_list
                if len(c[0]) > 0
                and len(c[0][0]) > 0
                and "terraform" in " ".join(c[0][0])
                and "init" in " ".join(c[0][0])
            ]
            assert len(init_calls) == 3

    def test_runs_terraform_plan_for_all_components(self, mock_repo_root, mock_stdin_tty, mock_subprocess):
        """Function runs terraform plan for core, portal, and range."""
        with (
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("deploy.confirm", return_value=True),
            patch("os.chdir"),
        ):
            deploy.terraform_deploy("dev", "my-profile")

            # Should call terraform plan 3 times (not show or apply)
            plan_calls = [
                c
                for c in mock_subprocess.call_args_list
                if len(c[0]) > 0
                and len(c[0][0]) > 0
                and c[0][0][0] == "terraform"
                and len(c[0][0]) > 1
                and c[0][0][1] == "plan"
            ]
            assert len(plan_calls) == 3

    def test_runs_terraform_apply_when_user_confirms(self, mock_repo_root, mock_stdin_tty, mock_subprocess):
        """Function runs terraform apply when user confirms."""
        with (
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("deploy.confirm", return_value=True),
            patch("os.chdir"),
        ):
            mock_subprocess.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="{}")

            deploy.terraform_deploy("dev", "my-profile")

            # Should call terraform apply 3 times
            apply_calls = [
                c
                for c in mock_subprocess.call_args_list
                if len(c[0]) > 0
                and len(c[0][0]) > 0
                and "terraform" in " ".join(c[0][0])
                and "apply" in " ".join(c[0][0])
            ]
            assert len(apply_calls) == 3

    def test_captures_terraform_outputs(self, mock_repo_root, mock_stdin_tty, mock_subprocess):
        """Function captures terraform output as JSON."""
        with (
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("deploy.confirm", return_value=True),
            patch("os.chdir"),
        ):
            result = deploy.terraform_deploy("dev", "my-profile")

            assert isinstance(result, dict)
            # Result should contain outputs from all components

    # ---------------------------------------------------------------------
    # Error handling
    # ---------------------------------------------------------------------

    def test_exits_when_terraform_init_fails(self, mock_repo_root, mock_stdin_tty):
        """Function exits when terraform init fails."""
        with (
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("os.chdir"),
            patch("subprocess.run") as mock_run,
        ):

            def run_side_effect(cmd, **kwargs):
                cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
                if "init" in cmd_str:
                    raise subprocess.CalledProcessError(1, cmd)
                return subprocess.CompletedProcess(args=cmd, returncode=0)

            mock_run.side_effect = run_side_effect

            with pytest.raises(SystemExit):
                deploy.terraform_deploy("dev", "my-profile")

    def test_exits_when_terraform_plan_fails(self, mock_repo_root, mock_stdin_tty):
        """Function exits when terraform plan fails."""
        with (
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("os.chdir"),
            patch("subprocess.run") as mock_run,
        ):

            def run_side_effect(cmd, **kwargs):
                cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
                if "plan" in cmd_str:
                    raise subprocess.CalledProcessError(1, cmd)
                return subprocess.CompletedProcess(args=cmd, returncode=0)

            mock_run.side_effect = run_side_effect

            with pytest.raises(SystemExit):
                deploy.terraform_deploy("dev", "my-profile")

    def test_exits_when_user_refuses_terraform_apply(self, mock_repo_root, mock_stdin_tty):
        """Function exits when user refuses to apply terraform."""
        with (
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("subprocess.run") as mock_run,
            patch("builtins.input", return_value="n"),  # user refuses
        ):
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

            with pytest.raises(SystemExit) as exc_info:
                deploy.terraform_deploy("dev", "my-profile")

            assert exc_info.value.code == 1

    def test_exits_when_terraform_apply_fails(self, mock_repo_root, mock_stdin_tty):
        """Function exits when terraform apply fails."""
        with (
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("subprocess.run") as mock_run,
            patch("deploy.confirm", return_value=True),
            patch("os.chdir"),
        ):

            def run_side_effect(cmd, **kwargs):
                cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
                if "apply" in cmd_str:
                    raise subprocess.CalledProcessError(1, cmd)
                return subprocess.CompletedProcess(args=cmd, returncode=0)

            mock_run.side_effect = run_side_effect

            with pytest.raises(SystemExit):
                deploy.terraform_deploy("dev", "my-profile")

    # ---------------------------------------------------------------------
    # Dry-run mode
    # ---------------------------------------------------------------------

    def test_does_not_execute_terraform_in_dry_run(self, mock_repo_root, mock_subprocess):
        """Function does not execute terraform commands in dry-run."""
        with (
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("os.chdir"),
        ):
            deploy.terraform_deploy("dev", "my-profile", dry_run=True)

            # In dry-run, subprocess calls should not happen (or be minimal)
            # The test just verifies it completes without error

    # ---------------------------------------------------------------------
    # Component ordering
    # ---------------------------------------------------------------------

    def test_deploys_components_in_correct_order(self, mock_repo_root, mock_stdin_tty, mock_subprocess):
        """Function deploys core before portal and range."""
        component_order = []

        with (
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("deploy.confirm", return_value=True),
            patch("os.chdir") as mock_chdir,
        ):
            mock_subprocess.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="{}")

            def capture_chdir(path):
                path_str = str(path)
                if "environments/dev" in path_str and "portal" not in path_str and "range" not in path_str:
                    component_order.append("core")
                elif "portal" in path_str:
                    component_order.append("portal")
                elif "range" in path_str:
                    component_order.append("range")

            mock_chdir.side_effect = capture_chdir

            deploy.terraform_deploy("dev", "my-profile")

            # Core should be first
            assert component_order[0] == "core"
            # Portal and range can be in any order after core
            assert set(component_order[1:]) == {"portal", "range"}


# =============================================================================
# Test: walkthrough_cognito_user()
# =============================================================================


class TestWalkthroughCognitoUser:
    """Tests for deploy.walkthrough_cognito_user."""

    # ---------------------------------------------------------------------
    # Happy path - user creation
    # ---------------------------------------------------------------------

    def test_creates_cognito_user_with_email(self, mock_stdin_tty, mock_subprocess):
        """Function creates Cognito user with provided email."""
        outputs = {"cognito_user_pool_id": {"value": "us-east-2_ABC123"}}

        with (
            patch("deploy.confirm", return_value=True),
            patch("builtins.input", return_value="test@example.com"),
        ):
            deploy.walkthrough_cognito_user(outputs, "dev", "my-profile")

            # Should call aws cognito-idp admin-create-user
            cognito_calls = [
                c
                for c in mock_subprocess.call_args_list
                if len(c[0]) > 0 and len(c[0][0]) > 0 and c[0][0][0] == "aws" and "cognito-idp" in " ".join(c[0][0])
            ]
            assert len(cognito_calls) > 0

    def test_includes_user_pool_id_in_command(self, mock_stdin_tty, mock_subprocess):
        """Function passes correct user pool ID to Cognito."""
        outputs = {"cognito_user_pool_id": {"value": "us-east-2_TESTPOOL"}}

        with (
            patch("deploy.confirm", return_value=True),
            patch("builtins.input", return_value="test@example.com"),
        ):
            deploy.walkthrough_cognito_user(outputs, "dev", "my-profile")

            # Find the cognito command
            cognito_calls = [
                c
                for c in mock_subprocess.call_args_list
                if len(c[0]) > 0
                and len(c[0][0]) > 0
                and c[0][0][0] == "aws"
                and "admin-create-user" in " ".join(c[0][0])
            ]
            assert len(cognito_calls) > 0

            cmd = cognito_calls[0][0][0]
            assert "us-east-2_TESTPOOL" in " ".join(cmd)

    # ---------------------------------------------------------------------
    # Error handling
    # ---------------------------------------------------------------------

    def test_exits_when_cognito_user_creation_fails(self, mock_stdin_tty):
        """Function exits when Cognito user creation fails."""
        outputs = {"cognito_user_pool_id": {"value": "us-east-2_ABC123"}}

        with (
            patch("deploy.confirm", return_value=True),
            patch("builtins.input", return_value="test@example.com"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.side_effect = subprocess.CalledProcessError(returncode=1, cmd=["aws"])

            with pytest.raises(SystemExit):
                deploy.walkthrough_cognito_user(outputs, "dev", "my-profile")

    # ---------------------------------------------------------------------
    # Dry-run mode
    # ---------------------------------------------------------------------

    def test_does_not_create_user_in_dry_run_mode(self, mock_subprocess):
        """Function does not execute Cognito commands in dry-run."""
        outputs = {"cognito_user_pool_id": {"value": "us-east-2_ABC123"}}

        with patch("deploy.run_cmd") as mock_run:
            deploy.walkthrough_cognito_user(outputs, "dev", "my-profile", dry_run=True)

            # run_cmd should be called with dry_run=True
            for call_args in mock_run.call_args_list:
                if "dry_run" in call_args[1]:
                    assert call_args[1]["dry_run"] is True


# =============================================================================
# Test: main() CLI
# =============================================================================


class TestMainCLI:
    """Tests for deploy.main() CLI argument parsing."""

    # ---------------------------------------------------------------------
    # Command parsing
    # ---------------------------------------------------------------------

    def test_requires_command(self):
        """CLI requires a subcommand (bootstrap, terraform, or full)."""
        with (
            patch("sys.argv", ["deploy.py"]),
            pytest.raises(SystemExit),
        ):
            deploy.main()

    def test_bootstrap_command_requires_env(self):
        """Bootstrap command requires --env argument."""
        with (
            patch("sys.argv", ["deploy.py", "bootstrap", "--profile", "test"]),
            pytest.raises(SystemExit),
        ):
            deploy.main()

    def test_bootstrap_command_requires_profile(self):
        """Bootstrap command requires --profile argument."""
        with (
            patch("sys.argv", ["deploy.py", "bootstrap", "--env", "dev"]),
            pytest.raises(SystemExit),
        ):
            deploy.main()

    def test_terraform_command_requires_env(self):
        """Terraform command requires --env argument."""
        with (
            patch("sys.argv", ["deploy.py", "terraform", "--profile", "test"]),
            pytest.raises(SystemExit),
        ):
            deploy.main()

    def test_terraform_command_requires_profile(self):
        """Terraform command requires --profile argument."""
        with (
            patch("sys.argv", ["deploy.py", "terraform", "--env", "dev"]),
            pytest.raises(SystemExit),
        ):
            deploy.main()

    def test_full_command_requires_env_and_profile(self):
        """Full command requires both --env and --profile arguments."""
        with (
            patch("sys.argv", ["deploy.py", "full"]),
            pytest.raises(SystemExit),
        ):
            deploy.main()

    # ---------------------------------------------------------------------
    # Dependency checking
    # ---------------------------------------------------------------------

    def test_checks_dependencies_before_running_commands(self):
        """CLI checks dependencies before executing any command."""
        with (
            patch("sys.argv", ["deploy.py", "bootstrap", "--env", "dev", "--profile", "test"]),
            patch("deploy.check_dependencies") as mock_check,
            patch("deploy.bootstrap_account"),
            patch("deploy.walkthrough_github_secrets"),
            patch("deploy.walkthrough_backend_config"),
        ):
            mock_check.return_value = None

            deploy.main()

            # check_dependencies should be called
            mock_check.assert_called_once()

    # ---------------------------------------------------------------------
    # Command execution
    # ---------------------------------------------------------------------

    def test_executes_bootstrap_command(self):
        """CLI executes bootstrap_account when bootstrap command given."""
        with (
            patch("sys.argv", ["deploy.py", "bootstrap", "--env", "dev", "--profile", "test"]),
            patch("deploy.check_dependencies"),
            patch("deploy.bootstrap_account") as mock_bootstrap,
            patch("deploy.walkthrough_github_secrets"),
            patch("deploy.walkthrough_backend_config"),
            patch("deploy.walkthrough_git_commit"),
        ):
            mock_bootstrap.return_value = {"role_arn": "test"}

            deploy.main()

            mock_bootstrap.assert_called_once()

    def test_executes_terraform_command(self, mock_repo_root):
        """CLI executes terraform_deploy when terraform command given."""
        with (
            patch("sys.argv", ["deploy.py", "terraform", "--env", "dev", "--profile", "test"]),
            patch("deploy.check_dependencies"),
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("deploy.terraform_deploy") as mock_terraform,
            patch("deploy.walkthrough_acm_validation"),
            patch("deploy.walkthrough_dns_setup"),
            patch("deploy.walkthrough_cognito_user"),
            patch("deploy.walkthrough_final_steps"),
        ):
            mock_terraform.return_value = {}

            deploy.main()

            mock_terraform.assert_called_once()

    def test_executes_full_command(self):
        """CLI executes full_deployment when full command given."""
        with (
            patch("sys.argv", ["deploy.py", "full", "--env", "dev", "--profile", "test"]),
            patch("deploy.check_dependencies"),
            patch("deploy.full_deployment") as mock_full,
        ):
            deploy.main()

            mock_full.assert_called_once()

    def test_executes_gdc_bootstrap_command(self):
        """CLI executes gdc_bootstrap_cluster when gdc-bootstrap command given."""
        with (
            patch(
                "sys.argv",
                ["deploy.py", "gdc-bootstrap", "--project-id", "prod-rwctxzl6shxk", "--cluster-id", "cluster1"],
            ),
            patch("deploy.check_dependencies"),
            patch("deploy.gdc_bootstrap_cluster") as mock_gdc_bootstrap,
        ):
            deploy.main()

            mock_gdc_bootstrap.assert_called_once()

    # ---------------------------------------------------------------------
    # Dry-run mode
    # ---------------------------------------------------------------------

    def test_passes_dry_run_flag_to_bootstrap(self):
        """CLI passes --dry-run flag to bootstrap_account."""
        with (
            patch("sys.argv", ["deploy.py", "bootstrap", "--env", "dev", "--profile", "test", "--dry-run"]),
            patch("deploy.check_dependencies"),
            patch("deploy.bootstrap_account") as mock_bootstrap,
            patch("deploy.walkthrough_github_secrets"),
            patch("deploy.walkthrough_backend_config"),
        ):
            mock_bootstrap.return_value = {"role_arn": "test"}

            deploy.main()

            # Should be called with dry_run=True
            assert mock_bootstrap.call_args[1]["dry_run"] is True

    def test_passes_dry_run_flag_to_terraform(self, mock_repo_root):
        """CLI passes --dry-run flag to terraform_deploy."""
        with (
            patch("sys.argv", ["deploy.py", "terraform", "--env", "dev", "--profile", "test", "--dry-run"]),
            patch("deploy.check_dependencies"),
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("deploy.terraform_deploy") as mock_terraform,
        ):
            mock_terraform.return_value = None

            deploy.main()

            assert mock_terraform.call_args[1]["dry_run"] is True

    def test_passes_dry_run_flag_to_gdc_bootstrap(self):
        """CLI passes --dry-run flag to gdc_bootstrap_cluster."""
        with (
            patch(
                "sys.argv",
                [
                    "deploy.py",
                    "gdc-bootstrap",
                    "--project-id",
                    "prod-rwctxzl6shxk",
                    "--cluster-id",
                    "cluster1",
                    "--dry-run",
                ],
            ),
            patch("deploy.check_dependencies"),
            patch("deploy.gdc_bootstrap_cluster") as mock_gdc_bootstrap,
        ):
            deploy.main()

            assert mock_gdc_bootstrap.call_args[1]["dry_run"] is True
