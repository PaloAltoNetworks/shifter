"""Base executor protocols, shared types, and common exceptions.

Defines the two structural executor ports plus the shared ``CommandResult``
dataclass and exception classes used across all executors:

- ``CommandExecutor`` — the guest command-execution port (``run_command`` /
  ``wait_for_ready`` / ``reboot_and_wait``) implemented by SSM/SSH/NGFW/guest
  transports and consumed by ``SetupOrchestrator``.
- ``ActionExecutor`` — the provider action-dispatch port
  (``execute_action(action, context)``) implemented by ``AWSExecutor`` and
  consumed by ``OpsOrchestrator``.

The two ports are deliberately distinct: guest command execution and provider
API actions have different semantics, so orchestrators depend on the port they
actually need rather than sniffing capabilities at runtime.
"""

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

# =============================================================================
# Shared Exceptions
# =============================================================================


class ExecutorError(Exception):
    """Base exception for all executors."""


class ExecutorConnectionError(ExecutorError):
    """Raised when the underlying transport cannot reach the target."""


class ExecutorCommandError(ExecutorError):
    """Raised when a command fails (non-zero exit code)."""

    def __init__(self, message: str, exit_code: int = -1, stderr: str = "") -> None:
        self.exit_code = exit_code
        self.stderr = stderr
        super().__init__(f"{message} (exit_code={exit_code})")


class ExecutorTimeoutError(ExecutorError):
    """Raised when an operation times out."""


# =============================================================================
# Shared Types
# =============================================================================


@dataclass
class CommandResult:
    """Result of a command execution.

    Attributes:
        success: Whether the command completed successfully (exit code 0).
        exit_code: The exit code from the command (-1 if not available).
        stdout: Standard output from the command.
        stderr: Standard error output from the command.
    """

    success: bool
    exit_code: int
    stdout: str
    stderr: str


@runtime_checkable
class CommandExecutor(Protocol):
    """Guest command-execution port.

    Implemented by the transports that run scripts/commands against a guest
    target (SSMExecutor, SSHExecutor, NGFWExecutor, GuestSSHExecutor,
    RangePodSSHExecutor) and consumed by ``SetupOrchestrator``.

    The protocol defines the minimal interface required:
    - run_command: Execute a command on a target
    - wait_for_ready: Wait for the target to be ready for commands
    - reboot_and_wait: Reboot the target and wait for it to accept commands
    """

    def run_command(
        self,
        instance_id: str,
        script: str,
        timeout_seconds: int = 300,
        document_name: str = "AWS-RunShellScript",
        stdin_input: str | None = None,
    ) -> CommandResult:
        """Execute a command on the target.

        Args:
            instance_id: Target identifier (instance_id, host IP, etc.)
            script: Command/script to execute
            timeout_seconds: Maximum time to wait for completion
            document_name: Shell/document family for the target OS
            stdin_input: Optional extra content piped after the main script

        Returns:
            CommandResult with success status, stdout, and stderr
        """
        ...

    def wait_for_ready(
        self,
        instance_id: str,
        timeout_seconds: int = 300,
        document_name: str = "AWS-RunShellScript",
    ) -> bool:
        """Wait for the target to be ready for commands.

        Args:
            instance_id: Target identifier
            timeout_seconds: Maximum time to wait

        Returns:
            True if target is ready
        """
        ...

    def reboot_and_wait(
        self,
        instance_id: str,
        timeout_seconds: int = 300,
        document_name: str = "AWS-RunShellScript",
    ) -> bool:
        """Reboot the target and wait for it to accept commands again."""
        ...


@runtime_checkable
class ActionExecutor(Protocol):
    """Provider action-dispatch port.

    Implemented by executors that dispatch named, allowlisted provider
    operations (currently ``AWSExecutor``) and consumed by ``OpsOrchestrator``.

    This is deliberately separate from ``CommandExecutor``: provider actions
    are not guest command execution. The executor owns the closed action
    allowlist and validates required parameters before any provider mutation.
    """

    def execute_action(self, action: str, context: dict[str, Any]) -> CommandResult:
        """Execute a named, allowlisted action using context parameters.

        Args:
            action: The action name (e.g. "start_instance").
            context: Parameters for the action; the executor extracts only the
                keys its allowlist declares for that action.

        Returns:
            CommandResult describing the outcome. Unknown actions and missing
            required parameters are reported as failed results, not raised.
        """
        ...
