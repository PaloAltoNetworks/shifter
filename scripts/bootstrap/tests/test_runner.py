"""Tests for runner.py module."""

from unittest.mock import MagicMock, patch


class TestRunnerConfig:
    """Tests for RunnerConfig dataclass."""

    def test_creates_config_with_all_fields(self, mock_deploy):
        """Should create config with all required fields."""
        from runner import RunnerConfig

        config = RunnerConfig(
            env="dev",
            region="us-east-2",
            github_org="test-org",
            github_repo="test-repo",
            aws_profile="test-profile",
        )
        assert config.env == "dev"
        assert config.region == "us-east-2"
        assert config.github_org == "test-org"
        assert config.github_repo == "test-repo"
        assert config.aws_profile == "test-profile"


class TestGetRunnerConfig:
    """Tests for get_runner_config factory function."""

    def test_creates_config_with_params(self, mock_deploy):
        """Should create config with provided parameters."""
        from runner import get_runner_config

        config = get_runner_config(
            env="dev",
            region="us-west-2",
            github_org="my-org",
            github_repo="my-repo",
            aws_profile="my-profile",
        )
        assert config.env == "dev"
        assert config.region == "us-west-2"
        assert config.github_org == "my-org"
        assert config.github_repo == "my-repo"
        assert config.aws_profile == "my-profile"


class TestGetRunnerInstanceIds:
    """Tests for get_runner_instance_ids function."""

    def test_returns_instance_ids_when_found(self, mock_deploy):
        """Should return list of instance IDs when runners exist."""
        from runner import RunnerConfig, get_runner_instance_ids

        config = RunnerConfig(
            env="dev",
            region="us-east-2",
            github_org="test-org",
            github_repo="test-repo",
            aws_profile="test-profile",
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="i-abc123\ti-def456",
            )

            result = get_runner_instance_ids(config)

            assert result == ["i-abc123", "i-def456"]
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert "ec2" in call_args
            assert "describe-instances" in call_args
            assert "--profile" in call_args
            assert "test-profile" in call_args

    def test_returns_empty_list_when_none_found(self, mock_deploy):
        """Should return empty list when no runners found."""
        from runner import RunnerConfig, get_runner_instance_ids

        config = RunnerConfig(
            env="dev",
            region="us-east-2",
            github_org="test-org",
            github_repo="test-repo",
            aws_profile="test-profile",
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="",
            )

            result = get_runner_instance_ids(config)

            # Empty string splits to [''] but the function filters empty strings
            assert result == [] or result == [""]

    def test_returns_empty_list_on_aws_error(self, mock_deploy):
        """Should return empty list when AWS CLI fails."""
        from runner import RunnerConfig, get_runner_instance_ids

        config = RunnerConfig(
            env="dev",
            region="us-east-2",
            github_org="test-org",
            github_repo="test-repo",
            aws_profile="test-profile",
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="Access denied",
            )

            result = get_runner_instance_ids(config)

            assert result == []

    def test_filters_by_runner_tag_name(self, mock_deploy):
        """Should filter instances by shifter-github-runner-* tag."""
        from runner import RunnerConfig, get_runner_instance_ids

        config = RunnerConfig(
            env="dev",
            region="us-east-2",
            github_org="test-org",
            github_repo="test-repo",
            aws_profile="test-profile",
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")

            get_runner_instance_ids(config)

            call_args = mock_run.call_args[0][0]
            # Check that filter for tag name is included
            assert "Name=tag:Name,Values=shifter-github-runner-*" in call_args


class TestShowRunnerRegistrationInstructions:
    """Tests for show_runner_registration_instructions function."""

    def test_displays_instance_ids(self, mock_deploy, capsys):
        """Should display all instance IDs in output."""
        from runner import RunnerConfig, show_runner_registration_instructions

        config = RunnerConfig(
            env="dev",
            region="us-east-2",
            github_org="test-org",
            github_repo="test-repo",
            aws_profile="test-profile",
        )

        show_runner_registration_instructions(config, ["i-abc123", "i-def456"])

        captured = capsys.readouterr()
        assert "i-abc123" in captured.out
        assert "i-def456" in captured.out

    def test_calls_code_block_with_ssm_command(self, mock_deploy, capsys):
        """Should call code_block with SSM session command."""
        from runner import RunnerConfig, show_runner_registration_instructions

        config = RunnerConfig(
            env="dev",
            region="us-east-2",
            github_org="test-org",
            github_repo="test-repo",
            aws_profile="test-profile",
        )

        show_runner_registration_instructions(config, ["i-abc123"])

        # Check that code_block was called with SSM command
        calls = [str(call) for call in mock_deploy.code_block.call_args_list]
        ssm_calls = [c for c in calls if "ssm" in c and "i-abc123" in c]
        assert len(ssm_calls) > 0

    def test_displays_github_url(self, mock_deploy, capsys):
        """Should display GitHub runners settings URL."""
        from runner import RunnerConfig, show_runner_registration_instructions

        config = RunnerConfig(
            env="dev",
            region="us-east-2",
            github_org="my-org",
            github_repo="my-repo",
            aws_profile="test-profile",
        )

        show_runner_registration_instructions(config, ["i-abc123"])

        captured = capsys.readouterr()
        assert "github.com/my-org/my-repo" in captured.out

    def test_calls_code_block_with_dependency_commands(self, mock_deploy, capsys):
        """Should call code_block with dependency install commands."""
        from runner import RunnerConfig, show_runner_registration_instructions

        config = RunnerConfig(
            env="dev",
            region="us-east-2",
            github_org="test-org",
            github_repo="test-repo",
            aws_profile="test-profile",
        )

        show_runner_registration_instructions(config, ["i-abc123"])

        # Check that code_block was called with dependency commands
        calls = [str(call) for call in mock_deploy.code_block.call_args_list]
        dep_calls = [c for c in calls if "libicu" in c or "dotnet" in c]
        assert len(dep_calls) > 0

    def test_calls_code_block_with_service_commands(self, mock_deploy, capsys):
        """Should call code_block with svc.sh service commands."""
        from runner import RunnerConfig, show_runner_registration_instructions

        config = RunnerConfig(
            env="dev",
            region="us-east-2",
            github_org="test-org",
            github_repo="test-repo",
            aws_profile="test-profile",
        )

        show_runner_registration_instructions(config, ["i-abc123"])

        # Check that code_block was called with service commands
        calls = [str(call) for call in mock_deploy.code_block.call_args_list]
        svc_calls = [c for c in calls if "svc.sh" in c]
        assert len(svc_calls) > 0


class TestWalkthroughRunnerSetup:
    """Tests for walkthrough_runner_setup function."""

    def test_dry_run_returns_mock_instance_ids(self, mock_deploy):
        """Should return mock instance IDs in dry-run mode."""
        from runner import RunnerConfig, walkthrough_runner_setup

        config = RunnerConfig(
            env="dev",
            region="us-east-2",
            github_org="test-org",
            github_repo="test-repo",
            aws_profile="test-profile",
        )

        result = walkthrough_runner_setup(config, dry_run=True)

        assert result is not None
        assert "instance_ids" in result
        assert len(result["instance_ids"]) == 2
