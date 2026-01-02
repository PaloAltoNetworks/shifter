"""Tests for engine service imports.

These tests verify that services are importable from the engine package
after migration from mission_control.
"""


class TestECSService:
    """Tests for ECS service import from engine.services.ecs."""

    def test_start_provisioning_importable(self):
        """start_provisioning is importable from engine.services.ecs."""
        from engine.services.ecs import start_provisioning

        assert callable(start_provisioning)

    def test_start_teardown_importable(self):
        """start_teardown is importable from engine.services.ecs."""
        from engine.services.ecs import start_teardown

        assert callable(start_teardown)

    def test_get_task_status_importable(self):
        """get_task_status is importable from engine.services.ecs."""
        from engine.services.ecs import get_task_status

        assert callable(get_task_status)


class TestSSHService:
    """Tests for SSH service import from engine.services.ssh."""

    def test_ssh_connection_importable(self):
        """SSHConnection is importable from engine.services.ssh."""
        from engine.services.ssh import SSHConnection

        assert SSHConnection is not None

    def test_ssh_connection_error_importable(self):
        """SSHConnectionError is importable from engine.services.ssh."""
        from engine.services.ssh import SSHConnectionError

        assert issubclass(SSHConnectionError, Exception)


class TestSecretsService:
    """Tests for Secrets service import from engine.services.secrets."""

    def test_get_ssh_key_importable(self):
        """get_ssh_key is importable from engine.services.secrets."""
        from engine.services.secrets import get_ssh_key

        assert callable(get_ssh_key)

    def test_secrets_error_importable(self):
        """SecretsError is importable from engine.services.secrets."""
        from engine.services.secrets import SecretsError

        assert issubclass(SecretsError, Exception)
