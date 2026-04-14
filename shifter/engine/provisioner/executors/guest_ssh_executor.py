"""SSH executor for guest OS setup over private networking.

This executor is used for GCP guest setup where we do not have an SSM-style
command plane. It talks directly to Linux and Windows guests over OpenSSH.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import time

from executors.base import (
    CommandResult,
    ExecutorCommandError,
    ExecutorConnectionError,
    ExecutorError,
    ExecutorTimeoutError,
)

logger = logging.getLogger(__name__)


# Backward-compatible aliases for shared exception types
GuestSSHExecutorError = ExecutorError
CommandError = ExecutorCommandError
TimeoutError = ExecutorTimeoutError


class GuestSSHConnectionError(ExecutorConnectionError):
    """Raised when SSH connection fails."""


class GuestSSHExecutor:
    """Execute shell or PowerShell scripts on guest instances via SSH."""

    DEFAULT_SSH_PORT = 22

    def __init__(
        self,
        private_key: str,
        username: str,
        port: int = DEFAULT_SSH_PORT,
        poll_interval_seconds: int = 10,
        connect_timeout_seconds: int = 10,
    ):
        self._username = username
        self._port = port
        self._poll_interval = poll_interval_seconds
        self._connect_timeout = connect_timeout_seconds

        fd, self._key_path = tempfile.mkstemp(prefix="guest_ssh_key_", suffix=".pem")
        try:
            os.write(fd, private_key.encode())
        finally:
            os.close(fd)

    def close(self) -> None:
        """Remove the temporary SSH key file."""
        if hasattr(self, "_key_path") and os.path.exists(self._key_path):
            os.unlink(self._key_path)

    def __enter__(self) -> GuestSSHExecutor:
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()

    def _build_ssh_args(self, host: str, remote_command: list[str]) -> list[str]:
        return [
            "ssh",
            "-i",
            self._key_path,
            "-p",
            str(self._port),
            "-o",
            "StrictHostKeyChecking=no",  # NOSONAR — freshly provisioned range guests
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            f"ConnectTimeout={self._connect_timeout}",
            "-o",
            "LogLevel=ERROR",
            f"{self._username}@{host}",
            *remote_command,
        ]

    def _get_remote_command(self, document_name: str) -> list[str]:
        if document_name == "AWS-RunPowerShellScript":
            return [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                "-",
            ]
        return ["bash", "-se"]

    def _build_command_input(self, script: str, stdin_input: str | None, document_name: str) -> str:
        parts: list[str] = []
        if document_name != "AWS-RunPowerShellScript":
            parts.append("set -euo pipefail")
        if script:
            parts.append(script.rstrip("\n"))
        if stdin_input:
            parts.append(stdin_input.rstrip("\n"))
        return "\n".join(parts) + "\n"

    def run_command(
        self,
        instance_id: str,
        script: str,
        timeout_seconds: int = 300,
        document_name: str = "AWS-RunShellScript",
        stdin_input: str | None = None,
    ) -> CommandResult:
        host = instance_id
        remote_command = self._get_remote_command(document_name)
        ssh_args = self._build_ssh_args(host, remote_command)
        command_input = self._build_command_input(script, stdin_input, document_name)

        logger.info("Running %s script over SSH on %s as %s", document_name, host, self._username)

        try:
            result = subprocess.run(  # noqa: S603  # NOSONAR — trusted ssh binary with controlled args
                ssh_args,
                input=command_input.encode(),
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise TimeoutError(f"SSH command timed out after {timeout_seconds}s on {host}") from e
        except FileNotFoundError as e:
            raise GuestSSHConnectionError("ssh binary not found. Ensure openssh-client is installed.") from e
        except OSError as e:
            raise GuestSSHConnectionError(f"SSH connection failed to {host}: {e}") from e

        stdout = result.stdout.decode("utf-8", errors="replace")
        stderr = result.stderr.decode("utf-8", errors="replace")
        return CommandResult(
            success=result.returncode == 0,
            exit_code=result.returncode,
            stdout=stdout,
            stderr=stderr,
        )

    def _probe_ready(self, host: str, document_name: str) -> bool:
        probe_script = "Write-Output ready" if document_name == "AWS-RunPowerShellScript" else "echo ready"
        try:
            result = self.run_command(
                instance_id=host,
                script=probe_script,
                timeout_seconds=max(self._connect_timeout + 5, 15),
                document_name=document_name,
            )
        except (GuestSSHConnectionError, TimeoutError):
            return False
        return result.success and "ready" in result.stdout.lower()

    def wait_for_ready(
        self,
        target: str,
        timeout_seconds: int = 300,
        document_name: str = "AWS-RunShellScript",
    ) -> bool:
        start_time = time.time()
        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                raise TimeoutError(f"SSH on {target} did not become available within {timeout_seconds}s")

            if self._probe_ready(target, document_name):
                logger.info("SSH ready on %s after %.1fs", target, elapsed)
                return True

            logger.info("Waiting for SSH on %s... (%.1fs / %ds)", target, elapsed, timeout_seconds)
            time.sleep(self._poll_interval)

    def wait_for_agent(
        self,
        host: str,
        timeout_seconds: int = 300,
        document_name: str = "AWS-RunShellScript",
    ) -> bool:
        """Backward-compatible alias for wait_for_ready."""
        return self.wait_for_ready(host, timeout_seconds=timeout_seconds, document_name=document_name)

    def reboot_and_wait(
        self,
        instance_id: str,
        timeout_seconds: int = 300,
        document_name: str = "AWS-RunShellScript",
    ) -> bool:
        host = instance_id
        reboot_script = (
            "Restart-Computer -Force" if document_name == "AWS-RunPowerShellScript" else "sudo shutdown -r now"
        )

        try:
            self.run_command(
                instance_id=host,
                script=reboot_script,
                timeout_seconds=min(timeout_seconds, 30),
                document_name=document_name,
            )
        except (GuestSSHConnectionError, TimeoutError):
            logger.info("SSH connection dropped during reboot of %s (expected)", host)

        start_time = time.time()
        offline_seen = False
        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                state = "after reconnect wait" if offline_seen else "before reboot was observed"
                raise TimeoutError(f"{host} did not become ready within {timeout_seconds}s ({state})")

            ready = self._probe_ready(host, document_name)
            if not offline_seen:
                if not ready:
                    offline_seen = True
                    logger.info("%s is rebooting; SSH is offline", host)
            elif ready:
                logger.info("%s is back online after reboot", host)
                return True

            time.sleep(self._poll_interval)
