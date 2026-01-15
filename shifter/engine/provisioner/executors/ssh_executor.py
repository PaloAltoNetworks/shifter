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

        # Test all three completion detection strategies
        results = []

        # Strategy 1: Idle timeout
        logger.info("=" * 70)
        logger.info("STRATEGY 1: IDLE TIMEOUT (3s without data)")
        logger.info("=" * 70)
        try:
            result = self._test_idle_timeout(host, commands, timeout_seconds)
            results.append(("idle_timeout", result))
            logger.info(f"✓ idle_timeout succeeded: {len(result.stdout)} bytes")
        except Exception as e:
            logger.error(f"✗ idle_timeout failed: {e}")
            results.append(("idle_timeout", None))

        # Strategy 2: Prompt detection
        logger.info("=" * 70)
        logger.info("STRATEGY 2: PROMPT DETECTION (look for admin@ prompt)")
        logger.info("=" * 70)
        try:
            result = self._test_prompt_detect(host, commands, timeout_seconds)
            results.append(("prompt_detect", result))
            logger.info(f"✓ prompt_detect succeeded: {len(result.stdout)} bytes")
        except Exception as e:
            logger.error(f"✗ prompt_detect failed: {e}")
            results.append(("prompt_detect", None))

        # Strategy 3: Subprocess with native ssh
        logger.info("=" * 70)
        logger.info("STRATEGY 3: SUBPROCESS (native ssh binary)")
        logger.info("=" * 70)
        try:
            result = self._test_subprocess(host, commands, timeout_seconds)
            results.append(("subprocess", result))
            logger.info(f"✓ subprocess succeeded: {len(result.stdout)} bytes")
        except Exception as e:
            logger.error(f"✗ subprocess failed: {e}")
            results.append(("subprocess", None))

        # Summary
        logger.info("=" * 70)
        logger.info("STRATEGY COMPARISON SUMMARY")
        logger.info("=" * 70)
        for strategy, result in results:
            if result:
                logger.info(f"{strategy}: SUCCESS - {len(result.stdout)} bytes, exit_code={result.exit_code}")
            else:
                logger.info(f"{strategy}: FAILED")

        # Return first successful result
        for strategy, result in results:
            if result and result.success:
                logger.info(f"Using result from: {strategy}")
                return result

        # If none succeeded, raise error
        raise CommandError("All strategies failed")

    def _test_idle_timeout(self, host: str, commands: str, timeout_seconds: int) -> CommandResult:
        """Test idle timeout strategy - consider done after 3s without data."""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # noqa: S507 nosec B507

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

            logger.info("Opening shell, sending command")
            channel = client.invoke_shell()
            channel.settimeout(timeout_seconds)
            channel.send(commands + "\n")  # nosec B601
            channel.send("exit\n")
            channel.shutdown_write()

            output = ""
            start_time = time.time()
            last_data_time = time.time()
            chunk_count = 0
            idle_threshold = 3.0

            while True:
                if channel.recv_ready():
                    chunk = channel.recv(4096).decode("utf-8", errors="replace")
                    chunk_count += 1
                    last_data_time = time.time()
                    logger.info(f"[IDLE] Chunk {chunk_count}: {len(chunk)}b")
                    logger.info(f"[IDLE] Content: {chunk!r}")
                    output += chunk

                idle_time = time.time() - last_data_time
                if idle_time > idle_threshold:
                    logger.info(f"[IDLE] Idle {idle_time:.1f}s - done")
                    while channel.recv_ready():
                        chunk = channel.recv(4096).decode("utf-8", errors="replace")
                        output += chunk
                    break

                if channel.exit_status_ready():
                    logger.info("[IDLE] Exit status ready")
                    while channel.recv_ready():
                        chunk = channel.recv(4096).decode("utf-8", errors="replace")
                        output += chunk
                    break

                if time.time() - start_time > timeout_seconds:
                    raise TimeoutError(f"idle_timeout strategy timed out")

                time.sleep(0.1)

            exit_code = channel.recv_exit_status() if channel.exit_status_ready() else -1
            elapsed = time.time() - start_time
            logger.info(f"[IDLE] Complete: {elapsed:.1f}s, {len(output)}b, exit={exit_code}")
            logger.info(f"[IDLE] Raw output:\n{output}")

            cleaned = self._clean_output(output, commands)
            logger.info(f"[IDLE] Cleaned output:\n{cleaned}")

            return CommandResult(success=True, exit_code=exit_code, stdout=cleaned, stderr="")

        finally:
            client.close()

    def _test_prompt_detect(self, host: str, commands: str, timeout_seconds: int) -> CommandResult:
        """Test prompt detection strategy - look for admin@ prompt."""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # noqa: S507 nosec B507

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

            logger.info("Opening shell, sending command")
            channel = client.invoke_shell()
            channel.settimeout(timeout_seconds)
            channel.send(commands + "\n")  # nosec B601
            channel.send("exit\n")
            channel.shutdown_write()

            output = ""
            start_time = time.time()
            chunk_count = 0

            while True:
                if channel.recv_ready():
                    chunk = channel.recv(4096).decode("utf-8", errors="replace")
                    chunk_count += 1
                    logger.info(f"[PROMPT] Chunk {chunk_count}: {len(chunk)}b")
                    logger.info(f"[PROMPT] Content: {chunk!r}")
                    output += chunk

                    # Check for prompt in recent output
                    if "admin@" in output[-200:] and ">" in output[-50:]:
                        logger.info("[PROMPT] Detected prompt - done")
                        time.sleep(0.5)
                        while channel.recv_ready():
                            chunk = channel.recv(4096).decode("utf-8", errors="replace")
                            output += chunk
                        break

                if channel.exit_status_ready():
                    logger.info("[PROMPT] Exit status ready")
                    while channel.recv_ready():
                        chunk = channel.recv(4096).decode("utf-8", errors="replace")
                        output += chunk
                    break

                if time.time() - start_time > timeout_seconds:
                    raise TimeoutError(f"prompt_detect strategy timed out")

                time.sleep(0.1)

            exit_code = channel.recv_exit_status() if channel.exit_status_ready() else -1
            elapsed = time.time() - start_time
            logger.info(f"[PROMPT] Complete: {elapsed:.1f}s, {len(output)}b, exit={exit_code}")
            logger.info(f"[PROMPT] Raw output:\n{output}")

            cleaned = self._clean_output(output, commands)
            logger.info(f"[PROMPT] Cleaned output:\n{cleaned}")

            return CommandResult(success=True, exit_code=exit_code, stdout=cleaned, stderr="")

        finally:
            client.close()

    def _test_subprocess(self, host: str, commands: str, timeout_seconds: int) -> CommandResult:
        """Test subprocess strategy - use native ssh binary."""
        import subprocess
        import tempfile

        logger.info(f"Using native ssh binary to connect to {host}")

        # Write private key to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pem', delete=False) as f:
            f.write(self._private_key)
            key_path = f.name

        try:
            import os
            os.chmod(key_path, 0o600)

            # Build ssh command
            ssh_cmd = [
                'ssh',
                '-i', key_path,
                '-o', 'StrictHostKeyChecking=no',
                '-o', 'UserKnownHostsFile=/dev/null',
                '-o', f'ConnectTimeout={min(30, timeout_seconds)}',
                f'{self._username}@{host}',
                commands
            ]

            logger.info(f"[SUBPROCESS] Running: {' '.join(ssh_cmd[:3])} ... {self._username}@{host} <command>")

            start_time = time.time()
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False
            )
            elapsed = time.time() - start_time

            logger.info(f"[SUBPROCESS] Complete: {elapsed:.1f}s, exit={result.returncode}")
            logger.info(f"[SUBPROCESS] Stdout ({len(result.stdout)}b):\n{result.stdout}")
            logger.info(f"[SUBPROCESS] Stderr ({len(result.stderr)}b):\n{result.stderr}")

            return CommandResult(
                success=result.returncode == 0,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr
            )

        finally:
            import os
            try:
                os.unlink(key_path)
            except Exception:
                pass

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
