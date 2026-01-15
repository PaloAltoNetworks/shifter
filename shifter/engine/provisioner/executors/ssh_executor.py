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

            logger.info(f"Executing command: {commands[:100]}...")
            logger.info("Opening interactive shell with invoke_shell()")
            channel = client.invoke_shell()
            channel.settimeout(timeout_seconds)

            # Send commands
            logger.info(f"Sending command: {commands[:100]}")
            channel.send(commands + "\n")  # nosec B601
            channel.send("exit\n")
            channel.shutdown_write()

            # Read output using prompt detection strategy
            # PAN-OS CLI shows a prompt like "admin@ngfw-user-1>" when ready
            output = ""
            start_time = time.time()
            chunk_count = 0

            logger.info("Reading output with prompt detection (looking for admin@ prompt)")

            while True:
                if channel.recv_ready():
                    chunk = channel.recv(4096).decode("utf-8", errors="replace")
                    chunk_count += 1
                    logger.info(f"Chunk {chunk_count}: {len(chunk)} bytes")
                    logger.debug(f"Chunk {chunk_count} content: {chunk!r}")
                    output += chunk

                    # Check for PAN-OS prompt pattern in recent output
                    if "admin@" in output[-200:] and ">" in output[-50:]:
                        logger.info("Detected PAN-OS prompt - command complete")
                        # Wait briefly for any trailing data
                        time.sleep(0.5)
                        while channel.recv_ready():
                            chunk = channel.recv(4096).decode("utf-8", errors="replace")
                            chunk_count += 1
                            logger.debug(f"Final chunk {chunk_count}: {len(chunk)} bytes")
                            output += chunk
                        break

                # Also check if channel naturally closed
                if channel.exit_status_ready():
                    logger.info("Channel exit status ready")
                    while channel.recv_ready():
                        chunk = channel.recv(4096).decode("utf-8", errors="replace")
                        chunk_count += 1
                        output += chunk
                    break

                # Overall timeout check
                elapsed = time.time() - start_time
                if elapsed > timeout_seconds:
                    logger.error(
                        f"Command timed out after {elapsed:.1f}s (received {chunk_count} chunks, {len(output)} bytes)"
                    )
                    raise TimeoutError(f"Command timed out after {timeout_seconds}s")

                time.sleep(0.1)

            # Get exit code if available
            exit_code = -1
            if channel.exit_status_ready():
                exit_code = channel.recv_exit_status()
                logger.info(f"Exit code: {exit_code}")
            else:
                logger.info("Exit status not ready - using -1")

            elapsed = time.time() - start_time
            logger.info(f"Command completed in {elapsed:.1f}s, received {len(output)} bytes in {chunk_count} chunks")
            logger.info(f"Raw output (first 1000 chars): {output[:1000]!r}")

            # Clean output
            cleaned = self._clean_output(output, commands)
            logger.info(f"Cleaned output: {len(cleaned)} bytes")
            logger.info(f"Cleaned output (first 500 chars): {cleaned[:500]}")

            return CommandResult(
                success=True,
                exit_code=exit_code,
                stdout=cleaned,
                stderr="",
            )

        except paramiko.SSHException as e:
            raise ConnectionError(f"SSH connection failed to {host}: {e}") from e
        except builtins.TimeoutError as e:
            raise TimeoutError(f"SSH command timed out on {host}") from e
        except OSError as e:
            raise TimeoutError(f"SSH command timed out on {host}: {e}") from e
        finally:
            client.close()

    def _clean_output(self, output: str, commands: str) -> str:
        """Clean output by removing prompts and command echo."""
        lines = output.split("\n")
        clean_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(self._username + "@"):
                continue
            if stripped == commands.strip():
                continue
            if stripped == "exit":
                continue
            clean_lines.append(line.rstrip())
        return "\n".join(clean_lines)

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
