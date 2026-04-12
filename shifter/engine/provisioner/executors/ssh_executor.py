"""SSH command executor for PAN-OS devices.

SSHExecutor uses SSH to execute CLI commands on PAN-OS devices (VM-Series).
Provides same interface as SSMExecutor for use with SetupOrchestrator.
"""

import builtins
import io
import logging
import time

import paramiko

from executors.base import (
    CommandResult,
    ExecutorCommandError,
    ExecutorConnectionError,
    ExecutorError,
    ExecutorTimeoutError,
)

logger = logging.getLogger(__name__)


# Backward-compatible aliases for shared exception types
SSHExecutorError = ExecutorError
CommandError = ExecutorCommandError
TimeoutError = ExecutorTimeoutError


class ConnectionError(ExecutorConnectionError):
    """Raised when SSH connection fails."""


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
        document_name: str = "",  # Unused, for Protocol compatibility with SSMExecutor
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
        del document_name
        host = instance_id
        client = paramiko.SSHClient()
        # Security context: AutoAddPolicy is acceptable because we connect to freshly
        # provisioned PAN-OS VMs in isolated VPC subnets. Host keys change on reprovision.
        client.set_missing_host_key_policy(
            paramiko.AutoAddPolicy()  # noqa: S507  # NOSONAR — freshly provisioned VMs in isolated VPC
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
            channel.send("set cli pager off\n")  # nosec B601  # NOSONAR — hardcoded operational command
            channel.send(commands + "\n")  # nosec B601  # NOSONAR — operational data, not user input
            channel.send("exit\n")
            channel.shutdown_write()

            # Read output until channel closes naturally
            # We send 'exit' and shutdown_write(), so PAN-OS will close the channel
            # when all commands complete. This is more reliable than prompt detection
            # since commits can take 30+ seconds.
            #
            # IMPORTANT: We must wait for eof_received, NOT exit_status_ready.
            # exit_status_ready() can return True before all data arrives, causing
            # truncated output. eof_received is the authoritative signal that the
            # server has finished sending all data.
            output = ""
            start_time = time.time()
            chunk_count = 0

            logger.info("Reading output until channel EOF")

            while True:
                # Read any available data
                if channel.recv_ready():
                    chunk = channel.recv(4096).decode("utf-8", errors="replace")
                    chunk_count += 1
                    logger.info(f"Chunk {chunk_count}: {len(chunk)} bytes")
                    logger.debug(f"Chunk {chunk_count} content: {chunk!r}")
                    output += chunk

                # Check if channel EOF (server finished sending all data)
                # This is the ONLY reliable way to know all output has been received
                if channel.eof_received:
                    logger.info("Channel EOF received - draining remaining data")
                    # Use blocking recv() to drain ALL remaining data
                    # recv_ready() only checks Paramiko's buffer, not kernel TCP buffer
                    # Set short timeout for drain phase
                    channel.settimeout(2)
                    while True:
                        try:
                            chunk = channel.recv(4096)
                            if not chunk:  # Empty bytes = channel closed, no more data
                                break
                            chunk_count += 1
                            logger.info(f"Drain chunk {chunk_count}: {len(chunk)} bytes")
                            output += chunk.decode("utf-8", errors="replace")
                        except builtins.TimeoutError:
                            logger.info("Drain timeout - no more data")
                            break
                    break

                # Overall timeout check
                elapsed = time.time() - start_time
                if elapsed > timeout_seconds:
                    logger.error(
                        f"Command timed out after {elapsed:.1f}s (received {chunk_count} chunks, {len(output)} bytes)"
                    )
                    raise TimeoutError(f"Command timed out after {timeout_seconds}s")

                time.sleep(0.1)

            # Get exit code - wait briefly if not ready yet
            # After EOF, exit status should arrive shortly
            exit_code = -1
            for _ in range(10):  # Wait up to 1 second
                if channel.exit_status_ready():
                    exit_code = channel.recv_exit_status()
                    logger.info(f"Exit code: {exit_code}")
                    break
                time.sleep(0.1)
            else:
                logger.info("Exit status not ready after 1s - using -1")

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

    def wait_for_ready(
        self,
        instance_id: str,
        timeout_seconds: int = 1800,
        document_name: str = "",
    ) -> bool:
        """Wait for PAN-OS SSH readiness with the shared executor signature."""
        del document_name
        return self.wait_for_agent(instance_id, timeout_seconds=timeout_seconds)

    def _check_ssh_available(self, host: str) -> bool:
        """Check if SSH is available and PAN-OS CLI is ready.

        Not only checks if SSH accepts connections, but also verifies
        the management plane can process CLI commands by running a simple
        test command.

        Uses invoke_shell() instead of exec_command() because PAN-OS
        does not support the SSH exec channel.
        """
        try:
            client = paramiko.SSHClient()
            # Security context: Same as run_command - freshly provisioned VMs in isolated VPC.
            client.set_missing_host_key_policy(
                paramiko.AutoAddPolicy()  # noqa: S507  # NOSONAR — freshly provisioned VMs in isolated VPC
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
            logger.info(f"SSH readiness check: connected to {host}")

            # Use interactive shell - PAN-OS does not support SSH exec channel
            channel = client.invoke_shell()
            time.sleep(2)
            channel.send("show system info\n")  # nosec B601  # NOSONAR — hardcoded diagnostic command
            time.sleep(3)

            output = ""
            while channel.recv_ready():
                output += channel.recv(65535).decode("utf-8", errors="replace")

            channel.send("exit\n")
            channel.close()
            client.close()

            # Verify command succeeded with valid system info output
            # Check for key fields that will always be present in valid output
            has_hostname = "hostname" in output
            has_ip = "ip-address" in output
            has_netmask = "netmask" in output
            is_ready = has_hostname and has_ip and has_netmask

            if is_ready:
                logger.info(f"SSH readiness check passed for {host}")
            else:
                logger.info(
                    f"SSH readiness check failed for {host}: "
                    f"hostname={has_hostname} ip-address={has_ip} netmask={has_netmask} "
                    f"output_length={len(output)} output={output!r:.500}"
                )

            return is_ready
        except Exception as exc:
            logger.info(f"SSH readiness check exception for {host}: {exc}")
            return False

    def reboot_and_wait(
        self,
        instance_id: str,
        timeout_seconds: int = 1800,
        document_name: str = "",  # Unused, for Protocol compatibility with SSMExecutor
    ) -> bool:
        """Reboot PAN-OS device and wait for it to come back.

        Args:
            instance_id: Target IP address (named for Protocol compatibility)
            timeout_seconds: Maximum time to wait for device to return
            document_name: Unused, for Protocol compatibility with SSMExecutor

        Returns:
            True if device is back online

        Raises:
            TimeoutError: If device doesn't come back in time
        """
        host = instance_id
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
