"""Tests for SSHExecutor - TDD: Write tests first, all must fail initially.

SSHExecutor uses SSH to execute CLI commands on PAN-OS devices (VM-Series).
Provides same interface as SSMExecutor for use with SetupOrchestrator.
"""

import io
from unittest.mock import MagicMock, patch

import pytest


# Mock RSA key for tests
MOCK_PRIVATE_KEY = """-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEAvL0000000000000000000000000000000000000000000000
0000000000000000000000000000000000000000000000000000000000000000
0000000000000000000000000000000000000000000000000000000000000000
-----END RSA PRIVATE KEY-----"""


class TestSSHExecutorImports:
    """Test that SSHExecutor can be imported."""

    def test_import_ssh_executor(self):
        """SSHExecutor module should be importable."""
        from executors.ssh_executor import SSHExecutor

        assert SSHExecutor is not None

    def test_import_command_result(self):
        """CommandResult dataclass should be importable."""
        from executors.ssh_executor import CommandResult

        assert CommandResult is not None

    def test_import_exceptions(self):
        """Exception classes should be importable."""
        from executors.ssh_executor import (
            SSHExecutorError,
            CommandError,
            TimeoutError as SSHTimeoutError,
            ConnectionError as SSHConnectionError,
        )

        assert SSHExecutorError is not None
        assert CommandError is not None
        assert SSHTimeoutError is not None
        assert SSHConnectionError is not None


class TestRunCommandHappyPath:
    """Test successful SSH command execution."""

    @patch("paramiko.RSAKey.from_private_key")
    @patch("paramiko.SSHClient")
    def test_run_command_success(self, mock_ssh_class, mock_rsa_key):
        """Command succeeds, returns result with stdout/stderr."""
        from executors.ssh_executor import SSHExecutor, CommandResult

        mock_client = MagicMock()
        mock_ssh_class.return_value = mock_client

        mock_stdout = MagicMock()
        mock_stdout.read.return_value = b"Connected: yes"
        mock_stdout.channel.recv_exit_status.return_value = 0
        mock_stderr = MagicMock()
        mock_stderr.read.return_value = b""

        mock_client.exec_command.return_value = (None, mock_stdout, mock_stderr)
        mock_rsa_key.return_value = MagicMock()

        executor = SSHExecutor(private_key=MOCK_PRIVATE_KEY)
        result = executor.run_command(
            host="10.0.0.1",
            script="show panorama-status",
            timeout_seconds=60,
        )

        assert isinstance(result, CommandResult)
        assert result.success is True
        assert result.exit_code == 0
        assert "Connected" in result.stdout
        assert result.stderr == ""

    @patch("paramiko.RSAKey.from_private_key")
    @patch("paramiko.SSHClient")
    def test_run_command_returns_stderr_on_success(self, mock_ssh_class, mock_rsa_key):
        """Command can succeed but still have stderr output."""
        from executors.ssh_executor import SSHExecutor

        mock_client = MagicMock()
        mock_ssh_class.return_value = mock_client

        mock_stdout = MagicMock()
        mock_stdout.read.return_value = b"Done"
        mock_stdout.channel.recv_exit_status.return_value = 0
        mock_stderr = MagicMock()
        mock_stderr.read.return_value = b"Warning: deprecated"

        mock_client.exec_command.return_value = (None, mock_stdout, mock_stderr)
        mock_rsa_key.return_value = MagicMock()

        executor = SSHExecutor(private_key=MOCK_PRIVATE_KEY)
        result = executor.run_command("10.0.0.1", "some-command", 60)

        assert result.success is True
        assert result.stderr == "Warning: deprecated"


class TestRunCommandExpectedFailures:
    """Test expected failure scenarios."""

    @patch("paramiko.RSAKey.from_private_key")
    @patch("paramiko.SSHClient")
    def test_run_command_nonzero_exit_raises(self, mock_ssh_class, mock_rsa_key):
        """Non-zero exit code raises CommandError."""
        from executors.ssh_executor import SSHExecutor, CommandError

        mock_client = MagicMock()
        mock_ssh_class.return_value = mock_client

        mock_stdout = MagicMock()
        mock_stdout.read.return_value = b""
        mock_stdout.channel.recv_exit_status.return_value = 1
        mock_stderr = MagicMock()
        mock_stderr.read.return_value = b"Command failed"

        mock_client.exec_command.return_value = (None, mock_stdout, mock_stderr)
        mock_rsa_key.return_value = MagicMock()

        executor = SSHExecutor(private_key=MOCK_PRIVATE_KEY)

        with pytest.raises(CommandError) as exc_info:
            executor.run_command("10.0.0.1", "exit 1", 60)

        assert exc_info.value.exit_code == 1
        assert "Command failed" in exc_info.value.stderr

    @patch("paramiko.RSAKey.from_private_key")
    @patch("paramiko.SSHClient")
    def test_run_command_connection_error_raises(self, mock_ssh_class, mock_rsa_key):
        """SSH connection failure raises ConnectionError."""
        import paramiko
        from executors.ssh_executor import (
            SSHExecutor,
            ConnectionError as SSHConnectionError,
        )

        mock_client = MagicMock()
        mock_ssh_class.return_value = mock_client
        mock_client.connect.side_effect = paramiko.SSHException("Connection refused")
        mock_rsa_key.return_value = MagicMock()

        executor = SSHExecutor(private_key=MOCK_PRIVATE_KEY)

        with pytest.raises(SSHConnectionError) as exc_info:
            executor.run_command("10.0.0.1", "show version", 60)

        assert "Connection refused" in str(exc_info.value)

    @patch("paramiko.RSAKey.from_private_key")
    @patch("paramiko.SSHClient")
    def test_run_command_timeout_raises(self, mock_ssh_class, mock_rsa_key):
        """Socket timeout raises TimeoutError."""
        import socket
        from executors.ssh_executor import SSHExecutor, TimeoutError as SSHTimeoutError

        mock_client = MagicMock()
        mock_ssh_class.return_value = mock_client
        mock_client.exec_command.side_effect = socket.timeout("timed out")
        mock_rsa_key.return_value = MagicMock()

        executor = SSHExecutor(private_key=MOCK_PRIVATE_KEY)

        with pytest.raises(SSHTimeoutError) as exc_info:
            executor.run_command("10.0.0.1", "long-command", 60)

        assert "timed out" in str(exc_info.value).lower()


class TestWaitForAgentHappyPath:
    """Test successful SSH wait scenarios."""

    @patch("paramiko.RSAKey.from_private_key")
    @patch("paramiko.SSHClient")
    @patch("time.sleep")
    @patch("time.time")
    def test_wait_for_agent_success_immediately(
        self, mock_time, mock_sleep, mock_ssh_class, mock_rsa_key
    ):
        """SSH available immediately returns True."""
        from executors.ssh_executor import SSHExecutor

        mock_client = MagicMock()
        mock_ssh_class.return_value = mock_client
        mock_rsa_key.return_value = MagicMock()
        mock_time.return_value = 0

        executor = SSHExecutor(private_key=MOCK_PRIVATE_KEY)
        result = executor.wait_for_agent("10.0.0.1", timeout_seconds=60)

        assert result is True

    @patch("paramiko.RSAKey.from_private_key")
    @patch("paramiko.SSHClient")
    @patch("time.sleep")
    @patch("time.time")
    def test_wait_for_agent_eventually_online(
        self, mock_time, mock_sleep, mock_ssh_class, mock_rsa_key
    ):
        """SSH becomes available after a few retries."""
        import paramiko
        from executors.ssh_executor import SSHExecutor

        mock_client = MagicMock()
        mock_ssh_class.return_value = mock_client
        mock_rsa_key.return_value = MagicMock()

        # Simulate time passing
        mock_time.side_effect = [0, 10, 20, 30]

        # First two connects fail, third succeeds
        mock_client.connect.side_effect = [
            paramiko.SSHException("Connection refused"),
            paramiko.SSHException("Connection refused"),
            None,  # Success
        ]

        executor = SSHExecutor(private_key=MOCK_PRIVATE_KEY, poll_interval_seconds=10)
        result = executor.wait_for_agent("10.0.0.1", timeout_seconds=60)

        assert result is True
        assert mock_client.connect.call_count == 3


class TestWaitForAgentExpectedFailures:
    """Test expected failure scenarios for SSH wait."""

    @patch("paramiko.RSAKey.from_private_key")
    @patch("paramiko.SSHClient")
    @patch("time.sleep")
    @patch("time.time")
    def test_wait_for_agent_timeout_raises(
        self, mock_time, mock_sleep, mock_ssh_class, mock_rsa_key
    ):
        """SSH never available raises TimeoutError."""
        import paramiko
        from executors.ssh_executor import SSHExecutor, TimeoutError as SSHTimeoutError

        mock_client = MagicMock()
        mock_ssh_class.return_value = mock_client
        mock_rsa_key.return_value = MagicMock()

        # Time passes beyond timeout
        mock_time.side_effect = [0, 30, 60, 90]

        # All connects fail
        mock_client.connect.side_effect = paramiko.SSHException("Connection refused")

        executor = SSHExecutor(private_key=MOCK_PRIVATE_KEY, poll_interval_seconds=30)

        with pytest.raises(SSHTimeoutError) as exc_info:
            executor.wait_for_agent("10.0.0.1", timeout_seconds=60)

        assert "not become available" in str(exc_info.value).lower()


class TestRebootAndWaitHappyPath:
    """Test successful reboot scenarios."""

    @patch("paramiko.RSAKey.from_private_key")
    @patch("paramiko.SSHClient")
    @patch("time.sleep")
    @patch("time.time")
    def test_reboot_and_wait_success(
        self, mock_time, mock_sleep, mock_ssh_class, mock_rsa_key
    ):
        """Reboot PAN-OS device and wait for it to come back."""
        import paramiko
        from executors.ssh_executor import SSHExecutor

        mock_client = MagicMock()
        mock_ssh_class.return_value = mock_client
        mock_rsa_key.return_value = MagicMock()

        # Simulate time passing
        mock_time.side_effect = [0, 10, 70, 80, 90]

        mock_stdout = MagicMock()
        mock_stdout.read.return_value = b"Rebooting"
        mock_stdout.channel.recv_exit_status.return_value = 0
        mock_stderr = MagicMock()
        mock_stderr.read.return_value = b""

        # First exec_command for reboot succeeds
        mock_client.exec_command.return_value = (None, mock_stdout, mock_stderr)

        # Connect fails during reboot, then succeeds
        mock_client.connect.side_effect = [
            None,  # Initial connect for reboot command
            paramiko.SSHException("Connection refused"),  # During reboot
            None,  # Device back online
        ]

        executor = SSHExecutor(private_key=MOCK_PRIVATE_KEY, poll_interval_seconds=10)
        result = executor.reboot_and_wait("10.0.0.1", timeout_seconds=1800)

        assert result is True


class TestSSHExecutorInitialization:
    """Test SSHExecutor initialization and configuration."""

    @patch("paramiko.RSAKey.from_private_key")
    def test_initialization_parses_private_key(self, mock_rsa_key):
        """SSHExecutor parses the provided private key."""
        from executors.ssh_executor import SSHExecutor

        mock_rsa_key.return_value = MagicMock()

        executor = SSHExecutor(private_key=MOCK_PRIVATE_KEY)

        mock_rsa_key.assert_called_once()
        assert executor is not None

    @patch("paramiko.RSAKey.from_private_key")
    def test_initialization_custom_port(self, mock_rsa_key):
        """SSHExecutor accepts custom SSH port."""
        from executors.ssh_executor import SSHExecutor

        mock_rsa_key.return_value = MagicMock()

        executor = SSHExecutor(private_key=MOCK_PRIVATE_KEY, port=2222)

        assert executor._port == 2222

    @patch("paramiko.RSAKey.from_private_key")
    def test_initialization_custom_username(self, mock_rsa_key):
        """SSHExecutor accepts custom username."""
        from executors.ssh_executor import SSHExecutor

        mock_rsa_key.return_value = MagicMock()

        executor = SSHExecutor(private_key=MOCK_PRIVATE_KEY, username="paloalto")

        assert executor._username == "paloalto"

    @patch("paramiko.RSAKey.from_private_key")
    def test_initialization_default_username_is_admin(self, mock_rsa_key):
        """SSHExecutor defaults to 'admin' username for PAN-OS."""
        from executors.ssh_executor import SSHExecutor

        mock_rsa_key.return_value = MagicMock()

        executor = SSHExecutor(private_key=MOCK_PRIVATE_KEY)

        assert executor._username == "admin"


class TestCommandResultDataclass:
    """Test CommandResult dataclass."""

    def test_command_result_attributes(self):
        """CommandResult has expected attributes."""
        from executors.ssh_executor import CommandResult

        result = CommandResult(
            success=True,
            exit_code=0,
            stdout="output",
            stderr="error",
        )

        assert result.success is True
        assert result.exit_code == 0
        assert result.stdout == "output"
        assert result.stderr == "error"


class TestCommandErrorException:
    """Test CommandError exception."""

    def test_command_error_attributes(self):
        """CommandError has exit_code and stderr attributes."""
        from executors.ssh_executor import CommandError

        error = CommandError("Command failed", exit_code=1, stderr="error output")

        assert error.exit_code == 1
        assert error.stderr == "error output"
        assert "exit_code=1" in str(error)
