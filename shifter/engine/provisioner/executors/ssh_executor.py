"""SSH command executor for PAN-OS devices.

SSHExecutor uses SSH to execute CLI commands on PAN-OS devices (VM-Series).
Provides same interface as SSMExecutor for use with SetupOrchestrator.
"""

import logging
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class SSHExecutorError(Exception):
    """Base exception for SSH executor errors."""

    pass


class CommandError(SSHExecutorError):
    """Raised when a command fails."""

    def __init__(self, message: str, exit_code: int = -1, stderr: str = ""):
        self.exit_code = exit_code
        self.stderr = stderr
        super().__init__(f"{message} (exit_code={exit_code})")


class TimeoutError(SSHExecutorError):
    """Raised when an operation times out."""

    pass


class ConnectionError(SSHExecutorError):
    """Raised when SSH connection fails."""

    pass


@dataclass
class CommandResult:
    """Result of a command execution."""

    success: bool
    exit_code: int
    stdout: str
    stderr: str


class SSHExecutor:
    """SSH command executor for PAN-OS devices.

    Executes CLI commands on VM-Series via SSH using subprocess.
    Same interface as SSMExecutor for orchestrator compatibility.
    """

    DEFAULT_USERNAME = "admin"
    DEFAULT_SSH_PORT = 22

    def __init__(
        self,
        private_key: str,
        username: str = DEFAULT_USERNAME,
        port: int = DEFAULT_SSH_PORT,
        poll_interval_seconds: int = 30,
    ):
        """Initialize SSH executor.

        Args:
            private_key: PEM-encoded private key string (RSA or Ed25519)
            username: SSH username (default: admin)
            port: SSH port (default: 22)
            poll_interval_seconds: How often to poll for availability
        """
        self._private_key = private_key
        self._username = username
        self._port = port
        self._poll_interval = poll_interval_seconds

        # Write the private key to a temp file for use with ssh command
        self._key_file_path = self._write_key_file(private_key)

    def _write_key_file(self, private_key: str) -> str:
        """Write private key to a temp file and return the path."""
        fd, path = tempfile.mkstemp(suffix=".pem")
        try:
            os.write(fd, private_key.encode())
        finally:
            os.close(fd)
        os.chmod(path, 0o600)
        return path

    def __del__(self):
        """Clean up the temp key file."""
        try:
            if hasattr(self, "_key_file_path") and os.path.exists(self._key_file_path):
                os.unlink(self._key_file_path)
        except Exception:
            logger.debug("Failed to clean up temp key file")

    def run_command(
        self,
        instance_id: str,
        script: str,
        timeout_seconds: int = 300,
        document_name: str | None = None,
        stdin_input: str | None = None,
    ) -> CommandResult:
        """Run a CLI command on a PAN-OS device via SSH.

        Uses subprocess with echo pipe to ssh for clean, predictable output.

        Args:
            instance_id: Target IP address or hostname.
            script: PAN-OS CLI command to execute
            timeout_seconds: Maximum time to wait for completion
            document_name: Ignored. For SetupOrchestrator compatibility.
            stdin_input: Additional commands to send after script.

        Returns:
            CommandResult with success status, exit code, stdout, stderr

        Raises:
            CommandError: If the command fails
            TimeoutError: If the command doesn't complete in time
            ConnectionError: If SSH connection fails
        """
        host = instance_id

        # Build the full command to send
        commands = script
        if stdin_input:
            commands = f"{commands}\n{stdin_input}"

        log_cmd = commands[:100]
        logger.info(f"Executing command on {host}: {log_cmd}...")

        # Build SSH command
        ssh_cmd = [
            "ssh",
            "-i",
            self._key_file_path,
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={min(30, timeout_seconds)}",
            "-p",
            str(self._port),
            f"{self._username}@{host}",
        ]

        try:
            # Pipe commands through stdin without shell=True
            result = subprocess.run(  # noqa: S603
                ssh_cmd,
                input=commands,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )

            logger.info(f"Command completed with exit code {result.returncode}")

            return CommandResult(
                success=result.returncode == 0,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )

        except subprocess.TimeoutExpired as e:
            raise TimeoutError(f"Command timed out after {timeout_seconds}s on {host}") from e
        except OSError as e:
            raise ConnectionError(f"SSH connection failed to {host}: {e}") from e

    def wait_for_agent(
        self,
        host: str,
        timeout_seconds: int = 1800,
    ) -> bool:
        """Wait for SSH to become available on a PAN-OS device.

        VM-Series takes 15-25 minutes to fully boot. This method polls
        until SSH responds.

        Args:
            host: Target IP address
            timeout_seconds: Maximum time to wait (default 30 min)

        Returns:
            True if SSH is available

        Raises:
            TimeoutError: If SSH doesn't become available in time
        """
        start_time = time.time()

        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                raise TimeoutError(f"SSH on {host} did not become available within {timeout_seconds}s")

            if self._check_ssh_available(host):
                logger.info(f"SSH available on {host} after {elapsed:.1f}s")
                return True

            logger.info(f"Waiting for SSH on {host}... ({elapsed:.1f}s / {timeout_seconds}s)")
            time.sleep(self._poll_interval)

    def _check_ssh_available(self, host: str) -> bool:
        """Check if SSH port is accepting connections and auth works."""
        try:
            ssh_cmd = [
                "ssh",
                "-i",
                self._key_file_path,
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "UserKnownHostsFile=/dev/null",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=10",
                "-p",
                str(self._port),
                f"{self._username}@{host}",
                "echo ok",
            ]

            result = subprocess.run(  # noqa: S603
                ssh_cmd,
                capture_output=True,
                text=True,
                timeout=15,
            )

            return result.returncode == 0

        except Exception:
            return False

    def reboot_and_wait(
        self,
        host: str,
        timeout_seconds: int = 1800,
    ) -> bool:
        """Reboot PAN-OS device and wait for it to come back.

        Args:
            host: Target IP address
            timeout_seconds: Maximum time to wait for device to return

        Returns:
            True if device is back online

        Raises:
            TimeoutError: If device doesn't come back in time
        """
        logger.info(f"Rebooting {host}...")

        # Issue reboot command
        try:
            self.run_command(
                instance_id=host,
                script="request restart system",
                timeout_seconds=30,
            )
        except (ConnectionError, CommandError, TimeoutError):
            # Connection may drop during reboot - that's expected
            logger.info("Connection dropped during reboot (expected)")

        # Wait for SSH to go down
        logger.info("Waiting for device to go offline...")
        time.sleep(60)

        # Wait for SSH to come back up
        logger.info("Waiting for device to come back online...")
        return self.wait_for_agent(host, timeout_seconds=timeout_seconds - 60)
