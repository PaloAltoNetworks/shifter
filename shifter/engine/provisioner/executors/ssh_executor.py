"""SSH command executor for PAN-OS devices.

SSHExecutor uses SSH to execute CLI commands on PAN-OS devices (VM-Series).
Provides same interface as SSMExecutor for use with SetupOrchestrator.
"""

import builtins
import io
import logging
import time
from dataclasses import dataclass

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

    Executes CLI commands on VM-Series via SSH using paramiko.
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

        # Parse the private key (supports RSA and Ed25519)
        self._pkey = self._load_private_key(private_key)

    def _load_private_key(self, private_key: str) -> paramiko.PKey:
        """Load a private key, detecting type automatically.

        Args:
            private_key: PEM-encoded private key string

        Returns:
            Paramiko key object (RSAKey or Ed25519Key)

        Raises:
            SSHExecutorError: If key type is unsupported or parsing fails
        """
        key_file = io.StringIO(private_key)

        # Try Ed25519 first (our default for NGFW)
        try:
            return paramiko.Ed25519Key.from_private_key(file_obj=key_file)
        except paramiko.SSHException:
            pass

        # Try RSA
        key_file.seek(0)
        try:
            return paramiko.RSAKey.from_private_key(file_obj=key_file)
        except paramiko.SSHException:
            pass

        raise SSHExecutorError("Unsupported key type. Only Ed25519 and RSA keys are supported.")

    def run_command(
        self,
        instance_id: str,
        script: str,
        timeout_seconds: int = 300,
        document_name: str | None = None,
        stdin_input: str | None = None,
    ) -> CommandResult:
        """Run a CLI command on a PAN-OS device via SSH.

        Uses paramiko invoke_shell() to send commands to the PAN-OS CLI.

        Args:
            instance_id: Target IP address or hostname. Named for SetupOrchestrator
                compatibility (SSM uses EC2 instance ID, SSH uses IP address).
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
        client = paramiko.SSHClient()
        # Security context: AutoAddPolicy is acceptable because we connect to freshly
        # provisioned PAN-OS VMs in isolated VPC subnets. Host keys change on reprovision.
        client.set_missing_host_key_policy(
            paramiko.AutoAddPolicy()  # noqa: S507
        )  # nosec B507

        # Build the full command to send via stdin
        commands = script
        if stdin_input:
            commands = f"{commands}\n{stdin_input}"

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

            log_cmd = commands[:100]
            logger.info(f"Executing command: {log_cmd}...")

            # PAN-OS requires invoke_shell() instead of exec_command()
            # exec_command() doesn't trigger the CLI, just shows the login banner
            logger.info("Opening interactive shell with invoke_shell()")
            channel = client.invoke_shell()
            channel.settimeout(timeout_seconds)

            # Send commands via stdin
            # Security: commands are from internal provisioning logic, not user input.
            logger.info(f"Sending command to shell: {commands[:100]}")
            channel.send(commands + "\n")  # nosec B601
            logger.info("Sending 'exit' to close shell")
            channel.send("exit\n")
            channel.shutdown_write()

            # Read all output from the channel
            output = ""
            start_time = time.time()
            chunk_count = 0
            while True:
                if channel.recv_ready():
                    chunk = channel.recv(4096).decode("utf-8", errors="replace")
                    chunk_count += 1
                    logger.debug(f"Received chunk {chunk_count} ({len(chunk)} bytes)")
                    output += chunk

                # Check if channel is closed
                if channel.exit_status_ready():
                    # Read any remaining data
                    while channel.recv_ready():
                        chunk = channel.recv(4096).decode("utf-8", errors="replace")
                        chunk_count += 1
                        logger.debug(f"Received final chunk {chunk_count} ({len(chunk)} bytes)")
                        output += chunk
                    break

                # Timeout check
                elapsed = time.time() - start_time
                if elapsed > timeout_seconds:
                    logger.error(f"Command timed out after {elapsed:.1f}s (received {chunk_count} chunks, {len(output)} bytes)")
                    raise TimeoutError(f"Command timed out after {timeout_seconds}s")

                time.sleep(0.1)

            exit_code = channel.recv_exit_status()
            logger.info(f"Command completed with exit code {exit_code}, received {len(output)} bytes in {chunk_count} chunks")
            logger.debug(f"Raw output (first 500 chars): {output[:500]!r}")

            # Clean up output: remove command echo and prompts
            # PAN-OS prompt format: "admin@ngfw-user-X> "
            lines = output.split("\n")
            logger.debug(f"Split output into {len(lines)} lines")
            clean_lines = []
            for line in lines:
                # Skip empty lines, prompts, and command echo
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith(self._username + "@"):
                    logger.debug(f"Skipping prompt line: {stripped[:50]}")
                    continue
                if stripped == commands.strip():
                    logger.debug(f"Skipping command echo: {stripped[:50]}")
                    continue
                if stripped == "exit":
                    logger.debug("Skipping 'exit' command")
                    continue
                clean_lines.append(line.rstrip())

            stdout_text = "\n".join(clean_lines)
            logger.info(f"Cleaned output: {len(clean_lines)} lines, {len(stdout_text)} bytes")
            logger.debug(f"Cleaned output (first 500 chars): {stdout_text[:500]!r}")

            return CommandResult(
                success=exit_code == 0,
                exit_code=exit_code,
                stdout=stdout_text,
                stderr="",  # invoke_shell() doesn't separate stderr
            )

        except paramiko.SSHException as e:
            raise ConnectionError(f"SSH connection failed to {host}: {e}") from e
        except builtins.TimeoutError as e:
            raise TimeoutError(f"SSH command timed out on {host}") from e
        except OSError as e:
            # Socket timeout raises OSError
            raise TimeoutError(f"SSH command timed out on {host}: {e}") from e
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
                raise TimeoutError(f"SSH on {host} did not become available within {timeout_seconds}s")

            if self._check_ssh_available(host):
                logger.info(f"SSH available on {host} after {elapsed:.1f}s")
                return True

            logger.info(f"Waiting for SSH on {host}... ({elapsed:.1f}s / {timeout_seconds}s)")
            time.sleep(self._poll_interval)

    def _check_ssh_available(self, host: str) -> bool:
        """Check if SSH port is accepting connections and auth works."""
        try:
            client = paramiko.SSHClient()
            # Security context: Same as run_command - freshly provisioned VMs in isolated VPC.
            client.set_missing_host_key_policy(
                paramiko.AutoAddPolicy()  # noqa: S507
            )  # nosec B507
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
        logger.info("Waiting for device to go offline...")
