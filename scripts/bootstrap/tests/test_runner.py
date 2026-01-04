"""Tests for runner.py module."""

import base64
from unittest.mock import MagicMock, patch


class TestRunnerConfig:
    """Tests for RunnerConfig dataclass."""

    def test_default_ssm_prefix(self, mock_deploy):
        """Should use default SSM prefix."""
        from runner import RunnerConfig

        config = RunnerConfig(
            env="dev",
            region="us-east-2",
            github_org="test-org",
            github_repo="test-repo",
        )
        assert config.ssm_prefix == "/shifter/github-runner"

    def test_key_param_name(self, mock_deploy):
        """Should construct correct key parameter name."""
        from runner import RunnerConfig

        config = RunnerConfig(
            env="dev",
            region="us-east-2",
            github_org="test-org",
            github_repo="test-repo",
        )
        assert config.key_param_name == "/shifter/github-runner/key-base64"

    def test_webhook_secret_param_name(self, mock_deploy):
        """Should construct correct webhook secret parameter name."""
        from runner import RunnerConfig

        config = RunnerConfig(
            env="dev",
            region="us-east-2",
            github_org="test-org",
            github_repo="test-repo",
        )
        assert config.webhook_secret_param_name == "/shifter/github-runner/webhook-secret"

    def test_custom_ssm_prefix(self, mock_deploy):
        """Should allow custom SSM prefix."""
        from runner import RunnerConfig

        config = RunnerConfig(
            env="prod",
            region="us-east-2",
            github_org="test-org",
            github_repo="test-repo",
            ssm_prefix="/custom/prefix",
        )
        assert config.key_param_name == "/custom/prefix/key-base64"
        assert config.webhook_secret_param_name == "/custom/prefix/webhook-secret"


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
        )
        assert config.env == "dev"
        assert config.region == "us-west-2"
        assert config.github_org == "my-org"
        assert config.github_repo == "my-repo"


class TestValidateBase64Pem:
    """Tests for validate_base64_pem function."""

    def test_valid_rsa_private_key(self, mock_deploy):
        """Should accept valid base64-encoded RSA private key."""
        from runner import validate_base64_pem

        # Minimal valid PEM structure (not a real key, just valid format)
        pem_content = "-----BEGIN RSA PRIVATE KEY-----\nMIIBogIBAAJB\n-----END RSA PRIVATE KEY-----\n"
        encoded = base64.b64encode(pem_content.encode()).decode()

        valid, msg = validate_base64_pem(encoded)
        assert valid is True
        assert msg == ""

    def test_valid_private_key(self, mock_deploy):
        """Should accept valid base64-encoded private key (generic)."""
        from runner import validate_base64_pem

        pem_content = "-----BEGIN PRIVATE KEY-----\nMIIBogIBAAJB\n-----END PRIVATE KEY-----\n"
        encoded = base64.b64encode(pem_content.encode()).decode()

        valid, msg = validate_base64_pem(encoded)
        assert valid is True
        assert msg == ""

    def test_invalid_base64(self, mock_deploy):
        """Should reject invalid base64."""
        from runner import validate_base64_pem

        valid, msg = validate_base64_pem("not-valid-base64!!!")
        assert valid is False
        assert "Invalid base64" in msg or "encoding" in msg.lower()

    def test_not_pem_format(self, mock_deploy):
        """Should reject content that's not PEM format."""
        from runner import validate_base64_pem

        encoded = base64.b64encode(b"just some random text").decode()

        valid, msg = validate_base64_pem(encoded)
        assert valid is False
        assert "PEM" in msg or "BEGIN" in msg

    def test_public_key_rejected(self, mock_deploy):
        """Should reject public keys (we need private key)."""
        from runner import validate_base64_pem

        pem_content = "-----BEGIN PUBLIC KEY-----\nMIIBogIBAAJB\n-----END PUBLIC KEY-----\n"
        encoded = base64.b64encode(pem_content.encode()).decode()

        valid, msg = validate_base64_pem(encoded)
        assert valid is False
        assert "private" in msg.lower()


class TestCheckSsmParameterExists:
    """Tests for check_ssm_parameter_exists function."""

    def test_returns_true_when_exists(self, mock_deploy):
        """Should return True when parameter exists."""
        from runner import check_ssm_parameter_exists

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            result = check_ssm_parameter_exists(
                "/test/param",
                "test-profile",
                "us-east-2",
            )

            assert result is True
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert "ssm" in call_args
            assert "get-parameter" in call_args
            assert "/test/param" in call_args

    def test_returns_false_when_not_exists(self, mock_deploy):
        """Should return False when parameter doesn't exist."""
        from runner import check_ssm_parameter_exists

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)

            result = check_ssm_parameter_exists(
                "/nonexistent/param",
                "test-profile",
                "us-east-2",
            )

            assert result is False


class TestCreateSsmParameter:
    """Tests for create_ssm_parameter function."""

    def test_creates_secure_string_by_default(self, mock_deploy):
        """Should create SecureString parameter by default."""
        from runner import create_ssm_parameter

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

            result = create_ssm_parameter(
                "/test/param",
                "secret-value",
                "test-profile",
                "us-east-2",
            )

            assert result is True
            call_args = mock_run.call_args[0][0]
            assert "--type" in call_args
            type_idx = call_args.index("--type")
            assert call_args[type_idx + 1] == "SecureString"

    def test_uses_overwrite_flag(self, mock_deploy):
        """Should use --overwrite flag."""
        from runner import create_ssm_parameter

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

            create_ssm_parameter(
                "/test/param",
                "secret-value",
                "test-profile",
                "us-east-2",
            )

            call_args = mock_run.call_args[0][0]
            assert "--overwrite" in call_args

    def test_returns_false_on_failure(self, mock_deploy):
        """Should return False when AWS CLI fails."""
        from runner import create_ssm_parameter

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="Access denied",
            )

            result = create_ssm_parameter(
                "/test/param",
                "secret-value",
                "test-profile",
                "us-east-2",
            )

            assert result is False

    def test_dry_run_does_not_call_aws(self, mock_deploy):
        """Should not call AWS in dry-run mode."""
        from runner import create_ssm_parameter

        with patch("subprocess.run") as mock_run:
            result = create_ssm_parameter(
                "/test/param",
                "secret-value",
                "test-profile",
                "us-east-2",
                dry_run=True,
            )

            assert result is True
            mock_run.assert_not_called()

    def test_includes_profile_and_region(self, mock_deploy):
        """Should include profile and region in AWS CLI call."""
        from runner import create_ssm_parameter

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

            create_ssm_parameter(
                "/test/param",
                "secret-value",
                "my-profile",
                "eu-west-1",
            )

            call_args = mock_run.call_args[0][0]
            assert "--profile" in call_args
            assert "my-profile" in call_args
            assert "--region" in call_args
            assert "eu-west-1" in call_args
