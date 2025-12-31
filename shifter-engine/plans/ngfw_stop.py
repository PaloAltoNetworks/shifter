"""NGFW Stop Plan for stopping a running NGFW instance.

This plan runs to stop a running NGFW:
- Stop EC2 instance via AWSExecutor.stop_instance()
- Wait for stopped state via AWSExecutor.wait_for_stopped()

Uses AWSExecutor methods for AWS API calls (not bash scripts).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class NGFWStopStep:
    """A step in the NGFW stop plan that uses AWSExecutor.

    Attributes:
        name: Unique identifier for this step.
        action: AWSExecutor method name to call.
        params: List of context keys to pass as method parameters.
    """

    name: str
    action: str
    params: List[str] = field(default_factory=list)


class NGFWStopPlan:
    """Stop plan for NGFW instance.

    Steps:
    1. Stop EC2 instance
    2. Wait for stopped state

    Uses AWSExecutor methods for AWS API calls.
    """

    name: str = "ngfw_stop"

    steps: List[NGFWStopStep] = [
        NGFWStopStep(
            name="stop_instance",
            action="stop_instance",
            params=["instance_id"],
        ),
        NGFWStopStep(
            name="wait_for_stopped",
            action="wait_for_stopped",
            params=["instance_id"],
        ),
    ]

    def get_context(self, instance: Any) -> Dict[str, Any]:
        """Get context variables for NGFW stop.

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
