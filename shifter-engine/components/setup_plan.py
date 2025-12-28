"""Setup plan framework for instance configuration.

SetupPlan defines a sequence of steps to configure an instance.
SetupStep represents a single step in the setup process.

This is an interface/protocol that specific plans implement.
"""

from dataclasses import dataclass, field
from typing import List, Protocol, Any, Dict


@dataclass
class SetupStep:
    """A single step in a setup plan.

    Attributes:
        name: Unique identifier for this step
        script: Script content to execute
        timeout_seconds: Maximum time to wait for step completion
        requires_reboot: If True, orchestrator will reboot after this step
        is_verification: If True, this is a check not an action
    """
    name: str
    script: str
    timeout_seconds: int = 300
    requires_reboot: bool = False
    is_verification: bool = False


class SetupPlan(Protocol):
    """Protocol for setup plans.

    Each instance type (DC, domain member, etc.) implements this protocol
    to define how it should be configured.
    """

    steps: List[SetupStep]
    """List of steps to execute in order."""

    verify_step: SetupStep
    """Final verification step to confirm setup succeeded."""

    def get_context(self, instance: Any) -> Dict[str, Any]:
        """Get template variables for rendering scripts.

        Args:
            instance: The instance being configured

        Returns:
            Dictionary of template variables
        """
        ...
