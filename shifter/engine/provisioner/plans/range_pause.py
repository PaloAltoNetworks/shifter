"""Range Pause Plan for stopping a running range instance.

This plan runs to stop a single range instance (attacker, victim, dc):
- Stop EC2 instance via AWSExecutor.stop_instance()
- Wait for stopped state via AWSExecutor.wait_for_stopped()

Uses AWSExecutor methods for AWS API calls (not bash scripts).
Note: Range pause executes this plan for each instance in the range.
"""

from dataclasses import dataclass
from typing import Any, ClassVar


@dataclass
class RangePauseStep:
    """A step in the range pause plan that names an allowlisted AWS action.

    Attributes:
        name: Unique identifier for this step.
        action: Allowlisted ``AWSExecutor.execute_action`` action name. The
            executor's allowlist is the single authority for the parameters the
            action requires from the run context.
    """

    name: str
    action: str


class RangePausePlan:
    """Pause plan for a single range instance.

    Steps:
    1. Stop EC2 instance
    2. Wait for stopped state

    Uses AWSExecutor methods for AWS API calls.
    """

    name: ClassVar[str] = "range_pause"

    steps: ClassVar[list[RangePauseStep]] = [
        RangePauseStep(
            name="stop_instance",
            action="stop_instance",
        ),
        RangePauseStep(
            name="wait_for_stopped",
            action="wait_for_stopped",
        ),
    ]

    @staticmethod
    def get_context(instance_id: str) -> dict[str, Any]:
        """Get context variables for range pause.

        Args:
            instance_id: AWS EC2 instance ID (e.g., i-abc123)

        Returns:
            Dict with context variables for AWSExecutor methods

        Raises:
            ValueError: If instance_id is missing
        """
        if not instance_id:
            raise ValueError("instance_id is required")

        return {
            "instance_id": instance_id,
        }
