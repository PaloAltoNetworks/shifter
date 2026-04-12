"""Base executor protocol, shared types, and common exceptions.

Defines the Executor protocol that all executors (SSM, SSH, AWS) must implement,
the CommandResult dataclass for returning execution results, and shared exception
classes used across all executors.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

# =============================================================================
# Shared Exceptions
# =============================================================================


class ExecutorError(Exception):
    """Base exception for all executors."""


class ExecutorConnectionError(ExecutorError):
    """Raised when the underlying transport cannot reach the target."""


class ExecutorCommandError(ExecutorError):
    """Raised when a command fails (non-zero exit code)."""

    def __init__(self, message: str, exit_code: int = -1, stderr: str = ""):
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
class Executor(Protocol):
    """Protocol for command executors.

    All executors (SSMExecutor, SSHExecutor, AWSExecutor) should implement
    this protocol to ensure consistent interfaces for orchestrators.

    The protocol defines the minimal interface required:
    - run_command: Execute a command on a target
    - wait_for_ready: Wait for the target to be ready for commands
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
