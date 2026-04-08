"""Generic SSH command executor for Linux and Windows VMs.

GenericSSHExecutor runs scripts on VMs via SSH using paramiko exec_command().
Designed for KubeVirt VMs on GKE where the provisioner pod can reach VM pod IPs
directly (no SSM agent needed).

Same Executor protocol as SSMExecutor — drop-in replacement for SetupOrchestrator.
"""

import io
import logging
import time

import paramiko

from executors.base import (
    CommandResult,
    ExecutorCommandError,
    ExecutorError,
    ExecutorTimeoutError,
)

logger = logging.getLogger(__name__)


class GenericSSHExecutor:
    """SSH command executor for Linux and Windows VMs.

    Executes scripts via SSH exec_command() (not invoke_shell() like the
    PAN-OS SSHExecutor). Compatible with SetupOrchestrator.

    Used by the GCP provisioner to configure KubeVirt VMs after boot.
    """

    DEFAULT_SSH_PORT = 22
    AGENT_POLL_INTERVAL = 10  # seconds between SSH readiness checks

    def __init__(
        self,
        private_key: str,
        username: str = "ubuntu",
        port: int = DEFAULT_SSH_PORT,
    ):
        """Initialize SSH executor.

        Args:
            private_key: PEM-encoded private key string (RSA or Ed25519).
            username: SSH username (ubuntu, kali, Administrator, etc.).
            port: SSH port.
        """
        self._private_key = private_key
        self._username = username
        self._port = port
        self._pkey = self._load_private_key(private_key)

    def _load_private_key(self, private_key: str) -> paramiko.PKey:
        """Load a private key, detecting type automatically."""
        key_file = io.StringIO(private_key)

        try:
            return paramiko.Ed25519Key.from_private_key(file_obj=key_file)
        except paramiko.SSHException:
            pass

        key_file.seek(0)
        try:
            return paramiko.RSAKey.from_private_key(file_obj=key_file)
        except paramiko.SSHException:
            pass

        raise ExecutorError("Unsupported key type. Only Ed25519 and RSA keys are supported.")

    def _connect(self, host: str, timeout: int = 30) -> paramiko.SSHClient:
        """Create an SSH connection to the target host."""
        client = paramiko.SSHClient()
        # KubeVirt VMs are freshly provisioned in isolated namespaces.
        client.set_missing_host_key_policy(
            paramiko.AutoAddPolicy()  # noqa: S507  # nosec B507 — ephemeral VMs in isolated K8s namespace
        )  # nosec B507

        client.connect(
            hostname=host,
            port=self._port,
            username=self._username,
            pkey=self._pkey,
            timeout=timeout,
            allow_agent=False,
            look_for_keys=False,
        )
        return client

    def run_command(
        self,
        instance_id: str,
        script: str,
        timeout_seconds: int = 300,
        document_name: str = "",
    ) -> CommandResult:
        """Run a script on a VM via SSH exec_command.

        Args:
            instance_id: Target IP address or hostname (VM pod IP on GKE).
            script: Shell script (Linux) or PowerShell script (Windows) to execute.
            timeout_seconds: Maximum time to wait for completion.
            document_name: Ignored. For SetupOrchestrator compatibility.

        Returns:
            CommandResult with success status, exit code, stdout, stderr.
        """
        host = instance_id
        client = None

        try:
            logger.info("SSH exec: connecting to %s:%d as %s", host, self._port, self._username)
            client = self._connect(host, timeout=30)

            logger.info("SSH exec: running script (%d chars) on %s", len(script), host)
            _, stdout_channel, stderr_channel = client.exec_command(
                script,
                timeout=timeout_seconds,
            )

            stdout = stdout_channel.read().decode("utf-8", errors="replace")
            stderr = stderr_channel.read().decode("utf-8", errors="replace")
            exit_code = stdout_channel.channel.recv_exit_status()

            success = exit_code == 0

            if success:
                logger.info("SSH exec: success on %s (exit_code=%d)", host, exit_code)
            else:
                logger.warning(
                    "SSH exec: failed on %s (exit_code=%d) stderr=%s",
                    host,
                    exit_code,
                    stderr[:200],
                )

            return CommandResult(
                success=success,
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
            )

        except paramiko.AuthenticationException as e:
            logger.error("SSH auth failed for %s: %s", host, e)
            raise ExecutorCommandError(f"SSH authentication failed: {e}", exit_code=-1) from e

        except paramiko.SSHException as e:
            logger.error("SSH error for %s: %s", host, e)
            raise ExecutorCommandError(f"SSH error: {e}", exit_code=-1) from e

        except TimeoutError as e:
            logger.error("SSH timeout for %s: %s", host, e)
            raise ExecutorTimeoutError(f"SSH command timed out after {timeout_seconds}s") from e

        except Exception as e:
            logger.exception("SSH unexpected error for %s", host)
            raise ExecutorError(f"SSH error: {e}") from e

        finally:
            if client:
                client.close()

    def wait_for_ready(
        self,
        target: str,
        timeout_seconds: int = 300,
    ) -> bool:
        """Wait for SSH to become available on the target.

        Polls until SSH connection succeeds or timeout.

        Args:
            target: IP address or hostname.
            timeout_seconds: Maximum time to wait.

        Returns:
            True if SSH is available.

        Raises:
            ExecutorTimeoutError: If SSH doesn't become available in time.
        """
        deadline = time.time() + timeout_seconds
        attempt = 0

        while time.time() < deadline:
            attempt += 1
            try:
                client = self._connect(target, timeout=10)
                client.close()
                logger.info("wait_for_ready: SSH available on %s (attempt %d)", target, attempt)
                return True
            except Exception:
                remaining = int(deadline - time.time())
                if remaining <= 0:
                    break
                logger.debug(
                    "wait_for_ready: SSH not ready on %s (attempt %d, %ds remaining)",
                    target,
                    attempt,
                    remaining,
                )
                time.sleep(self.AGENT_POLL_INTERVAL)

        raise ExecutorTimeoutError(f"SSH not available on {target} after {timeout_seconds}s ({attempt} attempts)")

    def wait_for_agent(self, instance_id: str, timeout_seconds: int = 300) -> bool:
        """Alias for wait_for_ready — SSMExecutor compatibility."""
        return self.wait_for_ready(instance_id, timeout_seconds)

    def reboot_instance(self, instance_id: str, timeout_seconds: int = 300) -> bool:
        """Reboot a VM and wait for SSH to come back.

        Args:
            instance_id: Target IP or hostname.
            timeout_seconds: Max time to wait for SSH after reboot.

        Returns:
            True if SSH is available after reboot.
        """
        logger.info("Rebooting %s via SSH", instance_id)

        import contextlib

        with contextlib.suppress(ExecutorCommandError, ExecutorError):
            self.run_command(instance_id, "sudo reboot", timeout_seconds=30)

        # Wait for SSH to come back
        logger.info("Waiting for %s to come back after reboot", instance_id)
        time.sleep(15)  # Give it time to actually shut down
        return self.wait_for_ready(instance_id, timeout_seconds)
