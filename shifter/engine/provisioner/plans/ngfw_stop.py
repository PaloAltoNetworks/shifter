"""NGFW Stop Plan for stopping a running NGFW instance.

This plan runs to stop a running NGFW:
- Stop EC2 instance via AWSExecutor.stop_instance()
- Wait for stopped state via AWSExecutor.wait_for_stopped()

Uses AWSExecutor methods for AWS API calls (not bash scripts).
"""

from dataclasses import dataclass
from typing import Any, ClassVar


@dataclass
class NGFWStopStep:
    """A step in the NGFW stop plan that names an allowlisted AWS action.

    Attributes:
        name: Unique identifier for this step.
        action: Allowlisted ``AWSExecutor.execute_action`` action name. The
            executor's allowlist is the single authority for the parameters the
            action requires from the run context.
    """

    name: str
    action: str


class NGFWStopPlan:
    """Stop plan for NGFW instance.

    Steps:
    1. Stop EC2 instance
    2. Wait for stopped state

    Uses AWSExecutor methods for AWS API calls.
    """

    name: ClassVar[str] = "ngfw_stop"

    steps: ClassVar[list[NGFWStopStep]] = [
        NGFWStopStep(
            name="stop_instance",
            action="stop_instance",
        ),
        NGFWStopStep(
            name="wait_for_stopped",
            action="wait_for_stopped",
        ),
    ]

    @staticmethod
    def get_context(instance: object) -> dict[str, Any]:
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
