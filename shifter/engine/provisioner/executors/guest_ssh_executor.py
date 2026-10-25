"""SSH executor for guest OS setup over private networking.

This executor is used for GCP guest setup where we do not have an SSM-style
command plane. It talks directly to Linux and Windows guests over OpenSSH.
"""

from __future__ import annotations

import base64
import contextlib
import logging
import os
import shlex
import subprocess
import tempfile
import threading
import time
from typing import IO, BinaryIO, cast

from executors.base import (
    CommandResult,
    ExecutorCommandError,
    ExecutorConnectionError,
    ExecutorError,
    ExecutorTimeoutError,
    GuestReadinessTimeoutError,
)

logger = logging.getLogger(__name__)


# Backward-compatible aliases for shared exception types
GuestSSHExecutorError = ExecutorError
CommandError = ExecutorCommandError
TimeoutError = ExecutorTimeoutError


class GuestSSHConnectionError(ExecutorConnectionError):
    """Raised when SSH connection fails."""


#: Chunk size for streaming a local file to a remote script's stdin.
_STREAM_CHUNK_BYTES = 1024 * 1024
#: Bound on captured stdout/stderr of a streamed run (setup scripts print markers).
_MAX_STREAMED_OUTPUT_BYTES = 1024 * 1024


#: Authored categories for a failed readiness probe, matched against the ssh
#: client's own diagnostics in order. Only the category leaves this module.
_PROBE_FAILURE_CATEGORIES: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("Host key verification failed", "REMOTE HOST IDENTIFICATION HAS CHANGED", "host key is known"),
        "host key not verifiable",
    ),
    (("Permission denied",), "authentication refused"),
    (("a password is required", "sudo:"), "privilege escalation refused"),
    (("Connection refused",), "connection refused"),
    (("timed out", "TimeoutError"), "connection timed out"),
    (("No route to host",), "no route to host"),
    (("exit=0",), "unexpected probe output"),
)


def _probe_failure_category(detail: str) -> str:
    """Map a probe's raw diagnostic onto one authored category."""
    for markers, category in _PROBE_FAILURE_CATEGORIES:
        if any(marker in detail for marker in markers):
            return category
    return "unavailable"


def _command_result(returncode: int, stdout_bytes: bytes, stderr_bytes: bytes) -> CommandResult:
    """Decode one ssh invocation's outcome into a ``CommandResult``."""
    return CommandResult(
        success=returncode == 0,
        exit_code=returncode,
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
    )


def _read_captured(handle: IO[bytes]) -> bytes:
    """Return the bounded head of a streamed run's captured output."""
    handle.seek(0)
    return handle.read(_MAX_STREAMED_OUTPUT_BYTES)


def _expire(process: subprocess.Popen[bytes], timed_out: threading.Event) -> None:
    """Watchdog action: mark the streamed run timed out and kill the ssh client."""
    timed_out.set()
    process.kill()


def _write_stream(stdin: IO[bytes], prefix: bytes, payload: BinaryIO) -> None:
    """Write ``prefix`` then ``payload`` to a process stdin in chunks, then close it.

    A remote that exits early (for example a failed free-space check) closes the
    pipe; the write stops and the exit status reports the failure.
    """
    try:
        if prefix:
            stdin.write(prefix)
        while chunk := payload.read(_STREAM_CHUNK_BYTES):
            stdin.write(chunk)
    except BrokenPipeError:
        pass
    finally:
        with contextlib.suppress(BrokenPipeError):
            stdin.close()


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
        host_public_key: str | None = None,
        known_hosts_host: str | None = None,
    ) -> None:
        self._username = username
        self._port = port
        self._poll_interval = poll_interval_seconds
        self._connect_timeout = connect_timeout_seconds
        self._last_probe_detail = ""
        self._key_path = self._provision_key(private_key)
        # When the provisioner installed a known host key on the guest (Linux
        # GDC guests, via cloud-init ssh_keys:), seed a dedicated known_hosts so
        # StrictHostKeyChecking=yes validates against a trusted-side-channel key
        # rather than failing on an empty known_hosts. Inert (None) otherwise.
        self._known_hosts_path: str | None = None
        if host_public_key and known_hosts_host:
            self._known_hosts_path = self._provision_known_hosts(known_hosts_host, host_public_key)

    def _provision_key(self, private_key: str) -> str:
        """Write the private key to a local temp file and return its path.

        Subclasses that run ssh on a remote transport (e.g. inside a range
        cluster pod) override this to return the key's path on that transport.
        """
        fd, key_path = tempfile.mkstemp(prefix="guest_ssh_key_", suffix=".pem")
        try:
            os.write(fd, private_key.encode())
        finally:
            os.close(fd)
        return key_path

    def _known_hosts_line(self, host: str, host_public_key: str) -> str:
        """Render the known_hosts entry, formatting non-default ports as [host]:port.

        OpenSSH keys known_hosts by ``host`` for :22 but by ``[host]:port`` for any
        other port, so a Docker-host guest reached on the management port (e.g. the
        container host on :2222) needs the bracketed form or strict checking
        fails to match the seeded key.
        """
        host_entry = host if self._port == self.DEFAULT_SSH_PORT else f"[{host}]:{self._port}"
        return f"{host_entry} {host_public_key.strip()}\n"

    def _provision_known_hosts(self, host: str, host_public_key: str) -> str:
        """Write a single-entry known_hosts file locally and return its path.

        Subclasses that run ssh on a remote transport override this to return a
        path on that transport (and plant the content there).
        """
        fd, path = tempfile.mkstemp(prefix="guest_known_hosts_", suffix="")
        try:
            os.write(fd, self._known_hosts_line(host, host_public_key).encode())
        finally:
            os.close(fd)
        return path

    def close(self) -> None:
        """Remove the temporary SSH key and known_hosts files."""
        if hasattr(self, "_key_path") and os.path.exists(self._key_path):
            os.unlink(self._key_path)
        known_hosts = getattr(self, "_known_hosts_path", None)
        if known_hosts and os.path.exists(known_hosts):
            os.unlink(known_hosts)

    def __enter__(self) -> GuestSSHExecutor:
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()

    def _build_ssh_args(self, host: str, remote_command: list[str]) -> list[str]:
        args = [
            "ssh",
            "-i",
            self._key_path,
            "-p",
            str(self._port),
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={self._connect_timeout}",
            "-o",
            "LogLevel=ERROR",
        ]
        if self._known_hosts_path:
            # Validate strictly against the provisioner-seeded host key only:
            # ignore the system known_hosts and pin ed25519 so the guest's
            # cloud-init-installed host key is the one negotiated and matched.
            args += [
                "-o",
                f"UserKnownHostsFile={self._known_hosts_path}",
                "-o",
                "GlobalKnownHostsFile=/dev/null",
                "-o",
                "HostKeyAlgorithms=ssh-ed25519",
            ]
        args += [f"{self._username}@{host}", *remote_command]
        return args

    @staticmethod
    def _get_remote_command(document_name: str) -> list[str]:
        # PowerShell scripts never reach here: run_command always delivers them via
        # -EncodedCommand (the `-Command -` stdin form silently returns empty
        # stdout for multi-line scripts over SSH). This path is the Linux shell.
        # Run guest shell setup as root, matching the AWS SSM RunShellScript
        # execution context (SSM runs as root; this SSH path logs in as an
        # unprivileged host user). Range setup needs root: writing under
        # root-owned image directories, installing systemd units, and configuring
        # guest firewall rules. The
        # guest images ship passwordless sudo for the login user (the reboot path
        # already relies on it); -n fails fast instead of hanging if that ever
        # regresses.
        return ["sudo", "-n", "bash", "-se"]

    @staticmethod
    def _build_command_input(script: str, stdin_input: str | None, document_name: str) -> str:
        parts: list[str] = []
        if document_name != "AWS-RunPowerShellScript":
            parts.append("set -euo pipefail")
        if script:
            parts.append(script.rstrip("\n"))
        if stdin_input:
            parts.append(stdin_input.rstrip("\n"))
        return "\n".join(parts) + "\n"

    def _remote_command(self, script: str, document_name: str, *, stdin_channel: bool) -> list[str]:
        """Return the guest command for ``script``; stdin stays free when ``stdin_channel``."""
        if document_name == "AWS-RunPowerShellScript":
            # Always deliver the PowerShell script through -EncodedCommand, never
            # `powershell -Command -` with the script piped on stdin. Piping a
            # multi-line script to `-Command -` over SSH silently returns exit 0
            # with EMPTY stdout on some Windows builds (valid `-EncodedCommand`,
            # empty `-Command -` during the OS-observation probe),
            # which fails the observation with no signal. The encoded-argv channel
            # is reliable and leaves stdin free for optional secret-bearing runtime
            # data, keeping credentials out of PowerShell source, argv, and env.
            encoded_script = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
            return [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                encoded_script,
            ]
        if stdin_channel:
            # Keep a secret-bearing Linux plan out of both the SSH command line
            # and the script stream. The non-secret script is base64-encoded in
            # argv and evaluated by a privileged child shell; stdin remains an
            # independent runtime-data channel consumed by that script.
            encoded_script = base64.b64encode(script.encode()).decode("ascii")
            wrapper = 'script=$(printf %s "$1" | base64 -d); exec bash -euo pipefail -c "$script"'
            return [
                "sudo",
                "-n",
                "bash",
                "-c",
                shlex.quote(wrapper),
                "shifter-setup",
                encoded_script,
            ]
        # Non-secret Linux script: piped to a privileged login shell on stdin.
        return self._get_remote_command(document_name)

    def run_command(
        self,
        instance_id: str,
        script: str,
        timeout_seconds: int = 300,
        document_name: str = "AWS-RunShellScript",
        stdin_input: str | None = None,
    ) -> CommandResult:
        host = instance_id
        stdin_channel = document_name == "AWS-RunPowerShellScript" or stdin_input is not None
        remote_command = self._remote_command(script, document_name, stdin_channel=stdin_channel)
        if stdin_channel:
            command_input = stdin_input or ""
        else:
            command_input = self._build_command_input(script, stdin_input, document_name)
        ssh_args = self._build_ssh_args(host, remote_command)

        logger.info("Running %s script over SSH on %s as %s", document_name, host, self._username)

        returncode, stdout_bytes, stderr_bytes = self._invoke_ssh(ssh_args, command_input.encode(), timeout_seconds)
        return _command_result(returncode, stdout_bytes, stderr_bytes)

    def run_command_streaming(
        self,
        instance_id: str,
        script: str,
        *,
        stdin_path: str,
        stdin_prefix: str = "",
        timeout_seconds: int = 300,
        document_name: str = "AWS-RunShellScript",
    ) -> CommandResult:
        """Run ``script`` with ``stdin_prefix`` and then the file at ``stdin_path`` on stdin.

        The script travels in argv exactly as for a ``stdin_input`` run, so stdin
        carries only runtime data, streamed with constant memory (ADR-032-R9).
        """
        remote_command = self._remote_command(script, document_name, stdin_channel=True)
        ssh_args = self._build_ssh_args(instance_id, remote_command)
        logger.info("Streaming %s script input over SSH on %s as %s", document_name, instance_id, self._username)
        returncode, stdout_bytes, stderr_bytes = self._invoke_ssh_streaming(
            ssh_args, stdin_prefix.encode(), stdin_path, timeout_seconds
        )
        return _command_result(returncode, stdout_bytes, stderr_bytes)

    def _invoke_ssh(self, ssh_args: list[str], command_input: bytes, timeout_seconds: int) -> tuple[int, bytes, bytes]:
        """Run the ssh client locally and return (returncode, stdout, stderr).

        This is the single transport seam: subclasses override it to run the
        same ssh invocation from a different vantage point (e.g. a pod inside
        the range cluster that has L2 reachability to the guest).
        """
        try:
            result = subprocess.run(  # noqa: S603  # NOSONAR — trusted ssh binary with controlled args
                ssh_args,
                input=command_input,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise TimeoutError(f"SSH command timed out after {timeout_seconds}s") from e
        except FileNotFoundError as e:
            raise GuestSSHConnectionError("ssh binary not found. Ensure openssh-client is installed.") from e
        except OSError as e:
            raise GuestSSHConnectionError(f"SSH subprocess failed: {e}") from e

        return result.returncode, result.stdout, result.stderr

    @staticmethod
    def _invoke_ssh_streaming(
        ssh_args: list[str], stdin_prefix: bytes, stdin_path: str, timeout_seconds: int
    ) -> tuple[int, bytes, bytes]:
        """Run the ssh client locally, streaming ``stdin_prefix`` + the file to its stdin.

        Output goes to temporary files rather than pipes so a chatty remote can
        never block the writer, and a watchdog kills the client at the deadline
        so a stalled transfer cannot hang the provisioner.
        """
        with (
            open(stdin_path, "rb") as payload,
            tempfile.TemporaryFile() as stdout_file,
            tempfile.TemporaryFile() as stderr_file,
        ):
            try:
                process = subprocess.Popen(  # noqa: S603  # NOSONAR — trusted ssh binary with controlled args
                    ssh_args, stdin=subprocess.PIPE, stdout=stdout_file, stderr=stderr_file
                )
            except FileNotFoundError as e:
                raise GuestSSHConnectionError("ssh binary not found. Ensure openssh-client is installed.") from e
            except OSError as e:
                raise GuestSSHConnectionError(f"SSH subprocess failed: {e}") from e
            timed_out = threading.Event()
            watchdog = threading.Timer(timeout_seconds, _expire, args=(process, timed_out))
            watchdog.start()
            try:
                _write_stream(cast(IO[bytes], process.stdin), stdin_prefix, payload)
                returncode = process.wait()
            finally:
                watchdog.cancel()
            if timed_out.is_set():
                raise TimeoutError(f"SSH command timed out after {timeout_seconds}s")
            return returncode, _read_captured(stdout_file), _read_captured(stderr_file)

    def _probe_ready(self, host: str, document_name: str) -> bool:
        probe_script = "Write-Output ready" if document_name == "AWS-RunPowerShellScript" else "echo ready"
        try:
            result = self.run_command(
                instance_id=host,
                script=probe_script,
                timeout_seconds=max(self._connect_timeout + 5, 15),
                document_name=document_name,
            )
        except (GuestSSHConnectionError, TimeoutError) as exc:
            self._last_probe_detail = f"{type(exc).__name__}: {exc}"
            return False
        if result.success and "ready" in result.stdout.lower():
            self._last_probe_detail = ""
            return True
        # Capture why the probe failed (e.g. host-key verification, auth,
        # connection refused) so a readiness timeout is diagnosable instead
        # of an opaque "did not become available".
        detail = (result.stderr or result.stdout or "").strip()
        self._last_probe_detail = f"exit={result.exit_code} {detail}".strip()
        return False

    def wait_for_ready(
        self,
        target: str,
        timeout_seconds: int = 300,
        document_name: str = "AWS-RunShellScript",
    ) -> bool:
        start_time = time.time()
        self._last_probe_detail = ""
        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                detail = self._last_probe_detail or "no probe diagnostic captured"
                logger.warning(
                    "SSH on %s did not become available within %ss (last probe: %s)", target, timeout_seconds, detail
                )
                raise GuestReadinessTimeoutError(
                    f"guest SSH did not become ready within {timeout_seconds}s: {_probe_failure_category(detail)}"
                )

            if self._probe_ready(target, document_name):
                logger.info("SSH ready on %s after %.1fs", target, elapsed)
                return True

            logger.info(
                "Waiting for SSH on %s... (%.1fs / %ds) last_probe=%s",
                target,
                elapsed,
                timeout_seconds,
                self._last_probe_detail or "(pending)",
            )
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
