"""NGFW command executor using SSH piping via subprocess.

Uses the ssh binary with stdin piping to send commands to PAN-OS devices.
This is the only reliable method for PAN-OS CLI interaction — paramiko's
exec_command() and invoke_shell() fail during boot and intermittently after.
"""

import logging
import os
import subprocess
import tempfile
import time

from executors.base import CommandResult, ExecutorError, ExecutorTimeoutError

logger = logging.getLogger(__name__)


# Backward-compatible aliases for shared exception types
NGFWExecutorError = ExecutorError
NGFWTimeoutError = ExecutorTimeoutError


class NGFWConnectionError(NGFWExecutorError):
    """Raised when SSH connection fails."""


class NGFWExecutor:
    """NGFW command executor using SSH piping via subprocess.

    Pipes commands to PAN-OS CLI via stdin, which is the only reliable
    method for interacting with PAN-OS SSH. No PTY, no pagination issues.

    Implements the same interface as SSHExecutor for drop-in replacement.
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
        self._username = username
        self._port = port
        self._poll_interval = poll_interval_seconds

        # Write PEM key to temp file — mkstemp creates with 0o600 (owner-only r/w)
        fd, self._key_path = tempfile.mkstemp(prefix="ngfw_key_", suffix=".pem")
        try:
            os.write(fd, private_key.encode())
        finally:
            os.close(fd)

    def close(self):
        """Remove temp key file."""
        if hasattr(self, "_key_path") and os.path.exists(self._key_path):
            os.unlink(self._key_path)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __del__(self):
        """Fallback cleanup if close() was not called."""
        self.close()

    def _build_ssh_args(self, host: str) -> list[str]:
        """Build the ssh command arguments."""
        return [
            "ssh",
            "-i",
            self._key_path,
            "-p",
            str(self._port),
            "-o",
            "StrictHostKeyChecking=no",  # NOSONAR — freshly provisioned VMs in isolated VPC
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "LogLevel=ERROR",
            f"{self._username}@{host}",
        ]

    def _build_command_input(self, script: str, stdin_input: str | None) -> str:
        """Build the full command string to pipe via stdin."""
        parts = []
        if script:
            parts.append(script.rstrip("\n"))
        if stdin_input:
            parts.append(stdin_input.rstrip("\n"))
        return "\n".join(parts) + "\n"

    def _is_system_info_ready(self, output: str) -> bool:
        """Check if show system info output indicates PAN-OS is ready."""
        return all(field in output for field in ("hostname", "ip-address", "netmask"))

    def run_command(
        self,
        instance_id: str,
        script: str,
        timeout_seconds: int = 300,
        document_name: str = "",
        stdin_input: str | None = None,
    ) -> CommandResult:
        """Run a CLI command on a PAN-OS device via SSH piping.

        Args:
            instance_id: Target IP address or hostname.
            script: PAN-OS CLI command to execute.
            timeout_seconds: Maximum time to wait for completion.
            document_name: Ignored. For SetupOrchestrator compatibility.
            stdin_input: Additional commands to send after script.

        Returns:
            CommandResult with success status, exit code, stdout, stderr.
        """
        host = instance_id
        command_input = self._build_command_input(script, stdin_input)
        ssh_args = self._build_ssh_args(host)

        logger.info("Piping command to %s: %s", host, command_input[:100])

        try:
            result = subprocess.run(  # noqa: S603  # NOSONAR — trusted ssh binary with controlled args
                ssh_args,
                input=command_input.encode(),
                capture_output=True,
                timeout=timeout_seconds,
            )

            stdout = result.stdout.decode("utf-8", errors="replace")
            stderr = result.stderr.decode("utf-8", errors="replace")

            logger.info(
                "Command completed: exit=%d stdout=%d bytes stderr=%d bytes",
                result.returncode,
                len(stdout),
                len(stderr),
            )

            return CommandResult(
                success=result.returncode == 0,
                exit_code=result.returncode,
                stdout=stdout,
                stderr=stderr,
            )

        except subprocess.TimeoutExpired as e:
            raise NGFWTimeoutError(f"Command timed out after {timeout_seconds}s on {host}") from e
        except FileNotFoundError as e:
            raise NGFWConnectionError("ssh binary not found. Ensure openssh-client is installed.") from e
        except OSError as e:
            raise NGFWConnectionError(f"SSH connection failed to {host}: {e}") from e

    def wait_for_agent(
        self,
        host: str,
        timeout_seconds: int = 1800,
    ) -> bool:
        """Wait for SSH and PAN-OS management plane to be ready.

        Polls by piping 'show system info' and checking for key fields.

        Args:
            host: Target IP address.
            timeout_seconds: Maximum time to wait (default 30 min).

        Returns:
            True if device is ready.

        Raises:
            NGFWTimeoutError: If device doesn't become ready in time.
        """
        start_time = time.time()

        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                raise NGFWTimeoutError(f"NGFW at {host} did not become available within {timeout_seconds}s")

            try:
                result = self.run_command(
                    instance_id=host,
                    script="show system info",
                    timeout_seconds=15,
                )
                if result.success and self._is_system_info_ready(result.stdout):
                    logger.info("NGFW ready at %s after %.1fs", host, elapsed)
                    return True
            except (NGFWTimeoutError, NGFWConnectionError):
                pass

            logger.info(
                "Waiting for NGFW at %s... (%.1fs / %ds)",
                host,
                elapsed,
                timeout_seconds,
            )
            time.sleep(self._poll_interval)

    # Alias for Executor protocol compatibility
    wait_for_ready = wait_for_agent

    def reboot_and_wait(
        self,
        instance_id: str,
        timeout_seconds: int = 1800,
        document_name: str = "",
    ) -> bool:
        """Reboot PAN-OS device and wait for it to come back.

        Args:
            instance_id: Target IP address.
            timeout_seconds: Maximum time to wait for device to return.
            document_name: Unused. For Protocol compatibility.

        Returns:
            True if device is back online.
        """
        host = instance_id
        logger.info("Rebooting %s...", host)

        try:
            self.run_command(
                instance_id=host,
                script="request restart system",
                timeout_seconds=30,
            )
        except (NGFWTimeoutError, NGFWConnectionError):
            logger.info("Connection dropped during reboot (expected)")

        logger.info("Waiting 60s for device to go offline...")
        time.sleep(60)

        logger.info("Waiting for device to come back online...")
        return self.wait_for_agent(host, timeout_seconds=timeout_seconds - 60)
