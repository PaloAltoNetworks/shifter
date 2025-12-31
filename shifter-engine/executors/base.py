"""Base executor protocol and shared types.

Defines the Executor protocol that all executors (SSM, SSH, AWS) must implement,
and the CommandResult dataclass for returning execution results.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class CommandResult:
    """Result of a command execution.

    Attributes:
        success: Whether the command completed successfully (exit code 0).
        stdout: Standard output from the command.
        stderr: Standard error output from the command.
    """

    success: bool
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
        target: str,
        script: str,
        timeout_seconds: int = 300,
        **kwargs,
    ) -> CommandResult:
        """Execute a command on the target.

        Args:
            target: Target identifier (instance_id, host IP, etc.)
            script: Command/script to execute
            timeout_seconds: Maximum time to wait for completion
            **kwargs: Additional executor-specific arguments

        Returns:
            CommandResult with success status, stdout, and stderr
        """
        ...

    def wait_for_ready(
        self,
        target: str,
        timeout_seconds: int = 300,
    ) -> bool:
        """Wait for the target to be ready for commands.

        Args:
            target: Target identifier
            timeout_seconds: Maximum time to wait

        Returns:
            True if target is ready
        """
        ...
