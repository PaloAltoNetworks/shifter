"""NGFW Start Plan for starting a stopped NGFW instance.

This plan runs to start a stopped NGFW:
- Start EC2 instance via AWSExecutor.start_instance()
- Wait for running state via AWSExecutor.wait_for_running()

Uses AWSExecutor methods for AWS API calls (not bash scripts).
"""

from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass
class NGFWStartStep:
    """A step in the NGFW start plan that uses AWSExecutor.

    Attributes:
        name: Unique identifier for this step.
        action: AWSExecutor method name to call.
        params: List of context keys to pass as method parameters.
    """

    name: str
    action: str
    params: list[str] = field(default_factory=list)


class NGFWStartPlan:
    """Start plan for NGFW instance.

    Steps:
    1. Start EC2 instance
    2. Wait for running state

    Uses AWSExecutor methods for AWS API calls.
    """

    name: ClassVar[str] = "ngfw_start"

    steps: ClassVar[list[NGFWStartStep]] = [
        NGFWStartStep(
            name="start_instance",
            action="start_instance",
            params=["instance_id"],
        ),
        NGFWStartStep(
            name="wait_for_running",
            action="wait_for_running",
            params=["instance_id"],
        ),
    ]

    def get_context(self, instance: Any) -> dict[str, Any]:
        """Get context variables for NGFW start.

        Args:
            instance: Instance with instance_id attribute

        Returns:
            Dict with context variables for AWSExecutor methods

        Raises:
            ValueError: If required attributes are missing
        """
        instance_id = getattr(instance, "instance_id", None)
        if not instance_id:
            raise ValueError("Instance missing required 'instance_id' attribute")

        return {
            "instance_id": instance_id,
        }
