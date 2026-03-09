"""Setup plan framework for instance configuration.

SetupPlan defines a sequence of steps to configure an instance.
SetupStep represents a single step in the setup process.

This is an interface/protocol that specific plans implement.
"""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class SetupStep:
    """A single step in a setup plan.

    Attributes:
        name: Unique identifier for this step
        script: Script content to execute (single command or script)
        timeout_seconds: Maximum time to wait for step completion
        requires_reboot: If True, orchestrator will reboot after this step
        is_verification: If True, this is a check not an action
        stdin_input: Multi-line input to pipe via stdin (for interactive modes
            like PAN-OS configure). If set, script may be empty.
        poll_for_job: If True, parse PAN-OS job ID from output and poll until
            complete. Used for async operations like content download/install.
    """

    name: str
    script: str
    timeout_seconds: int = 300
    requires_reboot: bool = False
    is_verification: bool = False
    stdin_input: str = ""
    poll_for_job: bool = False


class SetupPlan(Protocol):
    """Protocol for setup plans.

    Each instance type (DC, domain member, etc.) implements this protocol
    to define how it should be configured.

    Note: steps and verify_step may be ClassVar in implementations, which
    is compatible with this protocol (class variables are accessible as
    instance attributes).
    """

    @property
    def steps(self) -> list[SetupStep]:
        """List of steps to execute in order."""
        ...

    @property
    def verify_step(self) -> SetupStep | None:
        """Final verification step to confirm setup succeeded (optional)."""
        ...

    def get_context(self, instance: Any) -> dict[str, Any]:
        """Get template variables for rendering scripts.

        Args:
            instance: The instance being configured

        Returns:
            Dictionary of template variables
        """
        ...
