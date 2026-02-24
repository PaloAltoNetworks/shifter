"""Tests for local provisioner functionality."""

import logging
import os
from unittest.mock import MagicMock, patch
from uuid import UUID

TEST_REQUEST_ID = UUID("550e8400-e29b-41d4-a716-446655440000")


class TestIsLocalProvisionerEnabled:
    """Tests for _is_local_provisioner_enabled() function."""

    def test_returns_true_for_valid_modes(self, settings):
        """Returns True for valid LOCAL_PROVISIONER modes."""
        from engine.ecs import _is_local_provisioner_enabled

        settings.LOCAL_PROVISIONER = "subprocess"
        assert _is_local_provisioner_enabled() is True

        settings.LOCAL_PROVISIONER = "docker"
        assert _is_local_provisioner_enabled() is True

    def test_returns_false_for_invalid_or_missing(self, settings):
        """Returns False when LOCAL_PROVISIONER is not set, empty, or invalid."""
        from engine.ecs import _is_local_provisioner_enabled

        # Not set
        if hasattr(settings, "LOCAL_PROVISIONER"):
            delattr(settings, "LOCAL_PROVISIONER")
        assert _is_local_provisioner_enabled() is False

        # Empty string
        settings.LOCAL_PROVISIONER = ""
        assert _is_local_provisioner_enabled() is False

        # Invalid value
        settings.LOCAL_PROVISIONER = "invalid"
        assert _is_local_provisioner_enabled() is False


class TestRunLocalProvisioner:
    """Tests for _run_local_provisioner() function."""

    def test_returns_none_when_provisioner_not_found(self, settings, tmp_path):
        """Returns None when provisioner main.py doesn't exist."""
        from engine.ecs import _run_local_provisioner

        settings.PROVISIONER_PATH = str(tmp_path / "nonexistent")

        result = _run_local_provisioner(["range", "provision", "--request-id", "x"])

        assert result is None

    def test_sets_mock_pulumi_first_in_path(self, settings, tmp_path):
        """Puts mock-pulumi directory first in PATH."""
        from engine.ecs import _run_local_provisioner

        # Create fake provisioner
        provisioner_dir = tmp_path / "provisioner"
        provisioner_dir.mkdir()
        (provisioner_dir / "main.py").write_text("# fake")

        settings.PROVISIONER_PATH = str(provisioner_dir)
        settings.ENVIRONMENT = "dev"
        settings.AWS_REGION = "us-east-2"

        captured_env = {}

        def capture_popen(cmd, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            return mock_proc

        with patch("subprocess.Popen", side_effect=capture_popen):
            _run_local_provisioner(["range", "provision"])

        # Verify mock-pulumi dir is first in PATH
        path = captured_env.get("PATH", "")
        assert path.startswith(str(provisioner_dir))

    def test_passes_db_config_from_settings(self, settings, tmp_path):
        """Passes database config from Django settings."""
        from engine.ecs import _run_local_provisioner

        # Create fake provisioner
        provisioner_dir = tmp_path / "provisioner"
        provisioner_dir.mkdir()
        (provisioner_dir / "main.py").write_text("# fake")

        settings.PROVISIONER_PATH = str(provisioner_dir)
        settings.ENVIRONMENT = "dev"
        settings.AWS_REGION = "us-east-2"
        settings.DATABASES = {
            "default": {
                "HOST": "testhost",
                "PORT": 5433,
                "USER": "testuser",
                "PASSWORD": "testpass",
                "NAME": "testdb",
            }
        }

        captured_env = {}

        def capture_popen(cmd, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            return mock_proc

        # Clear any existing DB env vars so settings take precedence
        clean_env = {k: v for k, v in os.environ.items() if not k.startswith("DB_")}

        with (
            patch.dict(os.environ, clean_env, clear=True),
            patch("subprocess.Popen", side_effect=capture_popen),
        ):
            _run_local_provisioner(["range", "provision"])

        assert captured_env.get("DB_HOST") == "testhost"
        assert captured_env.get("DB_PORT") == "5433"
        assert captured_env.get("DB_USER") == "testuser"
        assert captured_env.get("DB_NAME") == "testdb"

    def test_returns_local_pid_on_success(self, settings, tmp_path):
        """Returns 'local-{pid}' format on success."""
        from engine.ecs import _run_local_provisioner

        # Create fake provisioner
        provisioner_dir = tmp_path / "provisioner"
        provisioner_dir.mkdir()
        (provisioner_dir / "main.py").write_text("# fake")

        settings.PROVISIONER_PATH = str(provisioner_dir)
        settings.ENVIRONMENT = "dev"
        settings.AWS_REGION = "us-east-2"

        mock_proc = MagicMock()
        mock_proc.pid = 99999

        with patch("subprocess.Popen", return_value=mock_proc):
            result = _run_local_provisioner(["range", "provision"])

        assert result == "local-99999"

    def test_logs_mock_pulumi_warning(self, settings, tmp_path, caplog):
        """Logs warning about mock pulumi usage."""
        from engine.ecs import _run_local_provisioner

        # Create fake provisioner
        provisioner_dir = tmp_path / "provisioner"
        provisioner_dir.mkdir()
        (provisioner_dir / "main.py").write_text("# fake")

        settings.PROVISIONER_PATH = str(provisioner_dir)
        settings.ENVIRONMENT = "dev"
        settings.AWS_REGION = "us-east-2"

        mock_proc = MagicMock()
        mock_proc.pid = 12345

        with (
            patch("subprocess.Popen", return_value=mock_proc),
            caplog.at_level(logging.INFO, logger="engine.ecs"),
        ):
            _run_local_provisioner(["range", "provision"])

        assert "mock" in caplog.text.lower() or "NO INFRA" in caplog.text


class TestNgfwProvisioningWithLocalMode:
    """Tests for NGFW provisioning when local mode is enabled."""

    def test_uses_local_provisioner_when_enabled(self, settings):
        """Uses local provisioner instead of ECS when enabled."""
        from engine.ecs import start_ngfw_provisioning

        settings.LOCAL_PROVISIONER = "subprocess"

        with patch("engine.ecs._run_local_provisioner") as mock_local:
            mock_local.return_value = "local-12345"

            result = start_ngfw_provisioning(request_id=TEST_REQUEST_ID)

            mock_local.assert_called_once()
            assert result == "local-12345"

    def test_local_provisioner_receives_correct_command(self, settings):
        """Local provisioner receives correct ngfw provision command."""
        from engine.ecs import start_ngfw_provisioning

        settings.LOCAL_PROVISIONER = "subprocess"

        with patch("engine.ecs._run_local_provisioner") as mock_local:
            mock_local.return_value = "local-12345"

            start_ngfw_provisioning(request_id=TEST_REQUEST_ID)

            call_args = mock_local.call_args[0][0]
            assert call_args == [
                "ngfw",
                "provision",
                "--request-id",
                str(TEST_REQUEST_ID),
            ]

    def test_does_not_call_ecs_when_local_enabled(self, settings):
        """Does not call ECS when local provisioner is enabled."""
        from engine.ecs import start_ngfw_provisioning

        settings.LOCAL_PROVISIONER = "subprocess"
        settings.AWS_REGION = "us-east-2"
        settings.PULUMI_ECS_CLUSTER_ARN = "arn:aws:ecs:cluster/test"
        settings.PULUMI_TASK_DEFINITION_ARN = "arn:aws:ecs:task/test"
        settings.PULUMI_ECS_SECURITY_GROUP_ID = "sg-123"
        settings.PULUMI_PRIVATE_SUBNET_IDS = "subnet-1"

        with (
            patch("engine.ecs._run_local_provisioner") as mock_local,
            patch("engine.ecs._get_ecs_client") as mock_ecs,
        ):
            mock_local.return_value = "local-12345"

            start_ngfw_provisioning(request_id=TEST_REQUEST_ID)

            mock_local.assert_called_once()
            mock_ecs.assert_not_called()


class TestRangeProvisioningWithLocalMode:
    """Tests for Range provisioning when local mode is enabled."""

    def test_uses_local_provisioner_when_enabled(self, settings):
        """Uses local provisioner instead of ECS when enabled."""
        from engine.ecs import start_range_provisioning

        settings.LOCAL_PROVISIONER = "subprocess"

        with patch("engine.ecs._run_local_provisioner") as mock_local:
            mock_local.return_value = "local-12345"

            result = start_range_provisioning(request_id=TEST_REQUEST_ID)

            mock_local.assert_called_once()
            assert result == "local-12345"

    def test_local_provisioner_receives_correct_command(self, settings):
        """Local provisioner receives correct range provision command."""
        from engine.ecs import start_range_provisioning

        settings.LOCAL_PROVISIONER = "subprocess"

        with patch("engine.ecs._run_local_provisioner") as mock_local:
            mock_local.return_value = "local-12345"

            start_range_provisioning(request_id=TEST_REQUEST_ID)

            call_args = mock_local.call_args[0][0]
            assert call_args == [
                "range",
                "provision",
                "--request-id",
                str(TEST_REQUEST_ID),
            ]


class TestNgfwTeardownWithLocalMode:
    """Tests for NGFW teardown when local mode is enabled."""

    def test_uses_local_provisioner_when_enabled(self, settings):
        """Uses local provisioner for teardown when enabled."""
        from engine.ecs import start_ngfw_teardown

        settings.LOCAL_PROVISIONER = "subprocess"

        with patch("engine.ecs._run_local_provisioner") as mock_local:
            mock_local.return_value = "local-12345"

            result = start_ngfw_teardown(request_id=TEST_REQUEST_ID)

            mock_local.assert_called_once()
            call_args = mock_local.call_args[0][0]
            assert "deprovision" in call_args
            assert result == "local-12345"
