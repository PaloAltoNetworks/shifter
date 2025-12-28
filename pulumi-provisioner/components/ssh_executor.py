"""SSH command executor for PAN-OS devices.

SSHExecutor uses SSH to execute CLI commands on PAN-OS devices (VM-Series).
Provides same interface as SSMExecutor for use with SetupOrchestrator.
"""

import io
import logging
import socket
import time
from dataclasses import dataclass
from typing import Optional

import paramiko

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

    Executes CLI commands on VM-Series via SSH.
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
            private_key: PEM-encoded private key string
            username: SSH username (default: admin)
            port: SSH port (default: 22)
            poll_interval_seconds: How often to poll for availability
        """
        self._private_key = private_key
        self._username = username
        self._port = port
        self._poll_interval = poll_interval_seconds

        # Parse the private key
        self._pkey = paramiko.RSAKey.from_private_key(file_obj=io.StringIO(private_key))

    def run_command(
        self,
        host: str,
        script: str,
        timeout_seconds: int = 300,
    ) -> CommandResult:
        """Run a CLI command on a PAN-OS device via SSH.

        Args:
            host: Target IP address or hostname
            script: PAN-OS CLI command to execute
            timeout_seconds: Maximum time to wait for completion

        Returns:
            CommandResult with success status, exit code, stdout, stderr

        Raises:
            CommandError: If the command fails
            TimeoutError: If the command doesn't complete in time
            ConnectionError: If SSH connection fails
        """
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            logger.info(f"Connecting to {host}:{self._port} as {self._username}")
            client.connect(
                hostname=host,
                port=self._port,
                username=self._username,
                pkey=self._pkey,
                timeout=30,
                allow_agent=False,
                look_for_keys=False,
            )

            logger.info(f"Executing command: {script[:100]}...")
            stdin, stdout, stderr = client.exec_command(
                script,
                timeout=timeout_seconds,
            )

            exit_code = stdout.channel.recv_exit_status()
            stdout_text = stdout.read().decode("utf-8")
            stderr_text = stderr.read().decode("utf-8")

            logger.info(f"Command completed with exit code {exit_code}")

            if exit_code != 0:
                raise CommandError(
                    f"Command failed on {host}",
                    exit_code=exit_code,
                    stderr=stderr_text,
                )

            return CommandResult(
                success=True,
                exit_code=exit_code,
                stdout=stdout_text,
                stderr=stderr_text,
            )

        except paramiko.SSHException as e:
            raise ConnectionError(f"SSH connection failed to {host}: {e}")
        except socket.timeout:
            raise TimeoutError(f"SSH command timed out on {host}")
        finally:
            client.close()

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
                raise TimeoutError(
                    f"SSH on {host} did not become available "
                    f"within {timeout_seconds}s"
                )

            if self._check_ssh_available(host):
                logger.info(f"SSH available on {host} after {elapsed:.1f}s")
                return True

            logger.info(
                f"Waiting for SSH on {host}... " f"({elapsed:.1f}s / {timeout_seconds}s)"
            )
            time.sleep(self._poll_interval)

    def _check_ssh_available(self, host: str) -> bool:
        """Check if SSH port is accepting connections and auth works."""
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                hostname=host,
                port=self._port,
                username=self._username,
                pkey=self._pkey,
                timeout=10,
                allow_agent=False,
                look_for_keys=False,
            )
            client.close()
            return True
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
            self.run_command(host, "request restart system", timeout_seconds=30)
        except (ConnectionError, CommandError, TimeoutError):
            # Connection may drop during reboot - that's expected
            logger.info("Connection dropped during reboot (expected)")

        # Wait for SSH to go down
        logger.info("Waiting for device to go offline...")
        time.sleep(60)

        # Wait for SSH to come back up
        logger.info("Waiting for device to come back online...")
        return self.wait_for_agent(host, timeout_seconds=timeout_seconds - 60)
