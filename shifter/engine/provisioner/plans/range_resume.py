"""Range Resume Plan for starting a stopped range instance.

This plan runs to start a single range instance (attacker, victim, dc):
- Start EC2 instance via AWSExecutor.start_instance()
- Wait for running state via AWSExecutor.wait_for_running()

Uses AWSExecutor methods for AWS API calls (not bash scripts).
Note: Range resume executes this plan for each instance in the range.
"""

from dataclasses import dataclass
from typing import Any, ClassVar


@dataclass
class RangeResumeStep:
    """A step in the range resume plan that names an allowlisted AWS action.

    Attributes:
        name: Unique identifier for this step.
        action: Allowlisted ``AWSExecutor.execute_action`` action name. The
            executor's allowlist is the single authority for the parameters the
            action requires from the run context.
    """

    name: str
    action: str


class RangeResumePlan:
    """Resume plan for a single range instance.

    Steps:
    1. Start EC2 instance
    2. Wait for running state

    Uses AWSExecutor methods for AWS API calls.
    """

    name: ClassVar[str] = "range_resume"

    steps: ClassVar[list[RangeResumeStep]] = [
        RangeResumeStep(
            name="start_instance",
            action="start_instance",
        ),
        RangeResumeStep(
            name="wait_for_running",
            action="wait_for_running",
        ),
    ]

    @staticmethod
    def get_context(instance_id: str) -> dict[str, Any]:
        """Get context variables for range resume.

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
