"""Behavior tests split from deploy.py: test_bootstrap_common.py.

Tests verify the complete contract for each function:
1. Inputs - minimum required data and validation
2. Outputs - return values and data structures
3. Side effects - subprocess calls, file writes, system changes
4. Errors - error handling and propagation
5. Logging - debug and error logging

All external dependencies are mocked. No actual AWS calls, file operations,
or subprocess executions occur during tests.
"""

import re
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

import deploy

PINNED_IMAGE_TAG = "abc1234"

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
                # ADR-008-R6 (#963): the GCP runtime renderer fails closed
                # without the Memorystore Secret Manager bundle ID.
                "redis": f"projects/{project_id}/secrets/shifter-gcp-dev-redis",
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
        # ADR-008-R6 (#963): Memorystore runs with TLS on the GCP runtime,
        # so the cache payload must carry tls_enabled or the renderer fails
        # closed.
        "control_plane_cache": {"value": {"host": "10.40.0.20", "port": 6378, "tls_enabled": True}},
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


# =============================================================================
# Split behavior tests
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
            urls = set(re.findall(r"https://[^\s)]+", captured.out))
            assert "https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html" in urls
            assert "https://developer.hashicorp.com/terraform/downloads" in urls
            assert "https://git-scm.com/downloads" in urls

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

    def test_state_bucket_secret_name_for_prod_env(self):
        """Prod uses the unsuffixed state-bucket secret name the prod deploy reads."""
        config = deploy.BootstrapConfig(env="prod")
        assert config.state_bucket_secret_name == "TF_INFRA_STATE_BUCKET"

    def test_state_bucket_secret_name_for_dev_env(self):
        """Dev uses the suffixed state-bucket secret name the dev deploy reads."""
        config = deploy.BootstrapConfig(env="dev")
        assert config.state_bucket_secret_name == "TF_INFRA_STATE_BUCKET_DEV"

    def test_state_bucket_secret_name_for_proof_env(self):
        """Proof uses the suffixed state-bucket secret name the proof deploy reads."""
        config = deploy.BootstrapConfig(env="proof")
        assert config.state_bucket_secret_name == "TF_INFRA_STATE_BUCKET_PROOF"

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
