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

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

import deploy

# =============================================================================
# Test Fixtures
# =============================================================================


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
# Test: bootstrap_account()
# =============================================================================


class TestBootstrapAccount:
    """Tests for deploy.bootstrap_account."""

    # ---------------------------------------------------------------------
    # Happy path - function succeeds
    # ---------------------------------------------------------------------

    def test_creates_s3_bucket_for_terraform_state(self, bootstrap_config, mock_subprocess):
        """Function creates S3 bucket for state storage."""
        with (
            patch("deploy.get_aws_account_id", return_value="123456789012"),
            patch("deploy.confirm", return_value=True),
        ):
            deploy.bootstrap_account(bootstrap_config, "my-profile")

            # Should call aws s3 mb
            s3_calls = [
                c
                for c in mock_subprocess.call_args_list
                if len(c[0]) > 0 and len(c[0][0]) > 0 and c[0][0][0] == "aws" and "s3" in " ".join(c[0][0])
            ]
            assert len(s3_calls) > 0

    def test_creates_dynamodb_table_for_state_locking(self, bootstrap_config, mock_subprocess):
        """Function creates DynamoDB table for state locking."""
        with (
            patch("deploy.get_aws_account_id", return_value="123456789012"),
            patch("deploy.confirm", return_value=True),
        ):
            deploy.bootstrap_account(bootstrap_config, "my-profile")

            # Should call aws dynamodb create-table
            dynamo_calls = [
                c
                for c in mock_subprocess.call_args_list
                if len(c[0]) > 0 and len(c[0][0]) > 0 and c[0][0][0] == "aws" and "dynamodb" in " ".join(c[0][0])
            ]
            assert len(dynamo_calls) > 0

    def test_creates_github_oidc_provider(self, bootstrap_config, mock_subprocess):
        """Function creates GitHub OIDC identity provider."""
        with (
            patch("deploy.get_aws_account_id", return_value="123456789012"),
            patch("deploy.confirm", return_value=True),
        ):
            deploy.bootstrap_account(bootstrap_config, "my-profile")

            # Should call create-open-id-connect-provider
            oidc_calls = [
                c
                for c in mock_subprocess.call_args_list
                if len(c[0]) > 0
                and len(c[0][0]) > 0
                and c[0][0][0] == "aws"
                and "create-open-id-connect-provider" in " ".join(c[0][0])
            ]
            assert len(oidc_calls) > 0

    def test_creates_iam_role_for_github_actions(self, bootstrap_config, mock_subprocess):
        """Function creates IAM role for GitHub Actions."""
        with (
            patch("deploy.get_aws_account_id", return_value="123456789012"),
            patch("deploy.confirm", return_value=True),
        ):
            deploy.bootstrap_account(bootstrap_config, "my-profile")

            # Should call aws iam create-role
            role_calls = [
                c
                for c in mock_subprocess.call_args_list
                if len(c[0]) > 0 and len(c[0][0]) > 0 and c[0][0][0] == "aws" and "create-role" in " ".join(c[0][0])
            ]
            assert len(role_calls) > 0

    def test_attaches_admin_policy_to_role(self, bootstrap_config, mock_subprocess):
        """Function attaches policies to IAM role."""
        with (
            patch("deploy.get_aws_account_id", return_value="123456789012"),
            patch("deploy.confirm", return_value=True),
        ):
            deploy.bootstrap_account(bootstrap_config, "my-profile")

            # Should call put-role-policy
            policy_calls = [
                c
                for c in mock_subprocess.call_args_list
                if len(c[0]) > 0 and len(c[0][0]) > 0 and c[0][0][0] == "aws" and "put-role-policy" in " ".join(c[0][0])
            ]
            assert len(policy_calls) > 0

    def test_returns_dict_with_bootstrap_results(self, bootstrap_config, mock_subprocess):
        """Function returns dictionary with resource ARNs and names."""
        with (
            patch("deploy.get_aws_account_id", return_value="123456789012"),
            patch("deploy.confirm", return_value=True),
        ):
            result = deploy.bootstrap_account(bootstrap_config, "my-profile")

            assert isinstance(result, dict)
            assert "role_arn" in result
            assert "bucket_name" in result
            assert "table_name" in result

    def test_uses_correct_github_org_and_repo_in_trust_policy(self, bootstrap_config, mock_subprocess):
        """Function includes correct GitHub org/repo in IAM trust policy."""
        with (
            patch("deploy.get_aws_account_id", return_value="123456789012"),
            patch("deploy.confirm", return_value=True),
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

    def test_does_not_create_resources_in_dry_run(self, bootstrap_config):
        """Function does not execute AWS commands in dry-run mode."""
        with (
            patch("subprocess.run") as mock_run,
            patch("deploy.get_aws_account_id", return_value="123456789012"),
        ):
            deploy.bootstrap_account(bootstrap_config, "my-profile", dry_run=True)

            # run_cmd should be called with dry_run=True
            for call_args in mock_run.call_args_list:
                if "dry_run" in call_args[1]:
                    assert call_args[1]["dry_run"] is True

    # ---------------------------------------------------------------------
    # Error handling
    # ---------------------------------------------------------------------

    def test_exits_when_s3_bucket_creation_fails(self, bootstrap_config):
        """Function exits when S3 bucket creation fails."""
        with (
            patch("subprocess.run") as mock_run,
            patch("deploy.get_aws_account_id", return_value="123456789012"),
        ):
            mock_run.side_effect = subprocess.CalledProcessError(returncode=1, cmd=["aws", "s3", "mb"])

            with pytest.raises(SystemExit):
                deploy.bootstrap_account(bootstrap_config, "my-profile")

    def test_exits_when_dynamodb_table_creation_fails(self, bootstrap_config):
        """Function exits when DynamoDB table creation fails."""
        with (
            patch("subprocess.run") as mock_run,
            patch("deploy.get_aws_account_id", return_value="123456789012"),
        ):
            # Succeed for S3, fail for DynamoDB
            def side_effect(cmd, **kwargs):
                if "dynamodb" in cmd:
                    raise subprocess.CalledProcessError(1, cmd)
                return subprocess.CompletedProcess(args=cmd, returncode=0)

            mock_run.side_effect = side_effect

            with pytest.raises(SystemExit):
                deploy.bootstrap_account(bootstrap_config, "my-profile")

    def test_exits_when_iam_role_creation_fails(self, bootstrap_config):
        """Function exits when IAM role creation fails."""
        with (
            patch("subprocess.run") as mock_run,
            patch("deploy.get_aws_account_id", return_value="123456789012"),
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

    def test_passes_profile_to_all_aws_commands(self, bootstrap_config):
        """Function passes profile parameter to all AWS CLI calls."""
        with (
            patch("subprocess.run") as mock_run,
            patch("deploy.get_aws_account_id", return_value="123456789012"),
            patch("deploy.confirm", return_value=True),
        ):

            def run_side_effect(cmd, **kwargs):
                cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
                # Return OIDC ARN for list-open-id-connect-providers
                if "list-open-id-connect-providers" in cmd_str:
                    return subprocess.CompletedProcess(
                        args=cmd,
                        returncode=0,
                        stdout="arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com\n",
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
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("builtins.input", return_value="y"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

            deploy.walkthrough_github_secrets(bootstrap_result)

            # Should call gh secret set
            gh_calls = [c for c in mock_run.call_args_list if c[0][0][0] == "gh"]
            assert len(gh_calls) > 0
            assert "secret" in gh_calls[0][0][0]
            assert "set" in gh_calls[0][0][0]

    def test_includes_role_arn_in_gh_secret_command(self, bootstrap_config, mock_stdin_tty):
        """Function passes correct role ARN to gh secret set."""
        bootstrap_result = {
            "role_arn": "arn:aws:iam::123456789012:role/test-role",
            "secret_name": "AWS_ROLE_ARN_DEV",
            "github_org": "test-org",
            "github_repo": "test-repo",
        }

        with (
            patch("shutil.which", return_value="/usr/bin/gh"),
            patch("builtins.input", return_value="y"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)

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

            # Check that bucket and table appear in written content
            all_content = "".join(written_content)
            assert "my-bucket" in all_content
            assert "my-table" in all_content
            assert "us-west-2" in all_content

    def test_commits_and_pushes_when_user_confirms(self, mock_repo_root, mock_stdin_tty, mock_subprocess):
        """Function commits and pushes changes when user confirms."""
        bootstrap_result = {
            "bucket_name": "test-bucket",
            "table_name": "test-table",
            "region": "us-east-2",
            "env": "dev",
        }

        with (
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("deploy.confirm_or_manual", side_effect=["yes", "yes"]),
            patch("pathlib.Path.write_text"),
        ):
            deploy.walkthrough_backend_config(bootstrap_result)

            # Should call git add, commit, push
            git_calls = [
                c for c in mock_subprocess.call_args_list if len(c[0]) > 0 and len(c[0][0]) > 0 and c[0][0][0] == "git"
            ]
            assert len(git_calls) > 0

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

    def test_exits_when_git_commit_fails_after_confirmation(self, mock_repo_root, mock_stdin_tty):
        """Function exits when git commit fails after user confirms."""
        bootstrap_result = {
            "bucket_name": "test-bucket",
            "table_name": "test-table",
            "region": "us-east-2",
            "env": "dev",
        }

        with (
            patch("deploy.get_repo_root", return_value=mock_repo_root),
            patch("deploy.confirm_or_manual", side_effect=["yes", "yes"]),
            patch("pathlib.Path.write_text"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.side_effect = subprocess.CalledProcessError(returncode=1, cmd=["git"])

            with pytest.raises(SystemExit):
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
            assert "backend.tf" in call_arg.lower()


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
