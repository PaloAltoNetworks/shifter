"""Behavior tests for local provisioner functionality.

``_run_local_provisioner`` shells out via ``subprocess.Popen`` (a real process
boundary), so these drive the real routing with ``Popen`` mocked at that
boundary and a temporary provisioner directory, instead of patching the
first-party ``_run_local_provisioner`` helper.
"""

import os
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

TEST_REQUEST_ID = UUID("550e8400-e29b-41d4-a716-446655440000")


@pytest.fixture
def local_provisioner(settings, tmp_path):
    """Enable subprocess local-provisioner mode with a fake provisioner dir.

    Yields a callable returning the captured ``subprocess.Popen`` mock so tests
    can assert the dispatched command without coupling to ECS.
    """
    provisioner_dir = tmp_path / "provisioner"
    provisioner_dir.mkdir()
    (provisioner_dir / "main.py").write_text("# fake")
    settings.LOCAL_PROVISIONER = "subprocess"
    settings.PROVISIONER_PATH = str(provisioner_dir)
    settings.ENVIRONMENT = "dev"
    settings.AWS_REGION = "us-east-2"

    proc = MagicMock()
    proc.pid = 12345
    with patch("subprocess.Popen", return_value=proc) as popen:
        yield popen


def _dispatched_command(popen):
    """Return the provisioner CLI args (without the leading python/main.py)."""
    full_command = popen.call_args[0][0]
    return full_command[2:]


class TestIsLocalProvisionerEnabled:
    def test_returns_true_for_valid_modes(self, settings):
        from engine.ecs import _is_local_provisioner_enabled

        settings.LOCAL_PROVISIONER = "subprocess"
        assert _is_local_provisioner_enabled() is True
        settings.LOCAL_PROVISIONER = "docker"
        assert _is_local_provisioner_enabled() is True

    def test_returns_false_for_invalid_or_missing(self, settings):
        from engine.ecs import _is_local_provisioner_enabled

        settings.LOCAL_PROVISIONER = ""
        assert _is_local_provisioner_enabled() is False
        settings.LOCAL_PROVISIONER = "invalid"
        assert _is_local_provisioner_enabled() is False


class TestRunLocalProvisioner:
    def test_returns_none_when_provisioner_not_found(self, settings, tmp_path):
        from engine.ecs import _run_local_provisioner

        settings.PROVISIONER_PATH = str(tmp_path / "nonexistent")
        assert _run_local_provisioner(["range", "provision", "--request-id", "x"]) is None

    def test_passes_db_config_from_settings(self, settings, tmp_path):
        from engine.ecs import _run_local_provisioner

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
            proc = MagicMock()
            proc.pid = 12345
            return proc

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
        from engine.ecs import _run_local_provisioner

        provisioner_dir = tmp_path / "provisioner"
        provisioner_dir.mkdir()
        (provisioner_dir / "main.py").write_text("# fake")
        settings.PROVISIONER_PATH = str(provisioner_dir)
        settings.ENVIRONMENT = "dev"
        settings.AWS_REGION = "us-east-2"

        proc = MagicMock()
        proc.pid = 99999
        with patch("subprocess.Popen", return_value=proc):
            assert _run_local_provisioner(["range", "provision"]) == "local-99999"


class TestNgfwProvisioningWithLocalMode:
    def test_routes_to_local_provisioner(self, local_provisioner):
        from engine.ecs import start_ngfw_provisioning

        result = start_ngfw_provisioning(request_id=TEST_REQUEST_ID)
        assert result == "local-12345"
        local_provisioner.assert_called_once()
        assert _dispatched_command(local_provisioner) == ["ngfw", "provision", "--request-id", str(TEST_REQUEST_ID)]

    def test_does_not_dispatch_to_ecs_when_local_enabled(self, local_provisioner, settings):
        from engine.ecs import start_ngfw_provisioning

        # ECS is fully configured, but local mode must win and never touch boto3.
        settings.ENGINE_TASK_CLUSTER = "test-cluster"
        settings.ENGINE_TASK_DEFINITION = "test-taskdef"
        settings.ENGINE_TASK_NETWORK_SECURITY_GROUP_ID = "sg-123"
        settings.ENGINE_TASK_NETWORK_SUBNET_IDS = "subnet-1"

        ecs = MagicMock()
        with patch("boto3.client", return_value=ecs):
            start_ngfw_provisioning(request_id=TEST_REQUEST_ID)

        local_provisioner.assert_called_once()
        ecs.run_task.assert_not_called()


class TestRangeProvisioningWithLocalMode:
    def test_routes_to_local_provisioner(self, local_provisioner):
        from engine.ecs import start_range_provisioning

        result = start_range_provisioning(request_id=TEST_REQUEST_ID)
        assert result == "local-12345"
        local_provisioner.assert_called_once()
        assert _dispatched_command(local_provisioner) == ["range", "provision", "--request-id", str(TEST_REQUEST_ID)]


class TestNgfwTeardownWithLocalMode:
    def test_routes_deprovision_to_local_provisioner(self, local_provisioner):
        from engine.ecs import start_ngfw_teardown

        result = start_ngfw_teardown(request_id=TEST_REQUEST_ID)
        assert result == "local-12345"
        assert "deprovision" in _dispatched_command(local_provisioner)
