"""UserNGFWStack Sweep Plan for idle NGFW detection.

This plan runs periodically to:
- Describe instances via AWSExecutor.describe_instances() to get current states
- Return instance states for orchestrator to determine idle status
- Orchestrator compares with DB activity data to identify idle instances

Uses AWSExecutor methods for AWS API calls (not bash scripts).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class UserNGFWStackSweepStep:
    """A step in the sweep plan that uses AWSExecutor.

    Attributes:
        name: Unique identifier for this step.
        action: AWSExecutor method name to call.
        params: List of context keys to pass as method parameters.
    """

    name: str
    action: str
    params: List[str] = field(default_factory=list)


class UserNGFWStackSweepPlan:
    """Sweep plan for idle NGFW detection.

    Steps:
    1. Describe instances to get current EC2 states

    The orchestrator uses returned states combined with DB activity data
    to identify idle instances that should be stopped.

    Uses AWSExecutor methods for AWS API calls.
    """

    name: str = "user_ngfw_stack_sweep"

    steps: List[UserNGFWStackSweepStep] = [
        UserNGFWStackSweepStep(
            name="describe_instances",
            action="describe_instances",
            params=["instance_ids"],
        ),
    ]

    def get_context(self, instance: Any) -> Dict[str, Any]:
        """Get context variables for sweep plan.

        Args:
            instance: Instance with instance_ids list and idle_threshold_minutes

        Returns:
            Dict with context variables for AWSExecutor methods

        Raises:
            ValueError: If required attributes are missing
        """
        instance_ids = getattr(instance, "instance_ids", None)
        if instance_ids is None:
            raise ValueError("Instance missing required 'instance_ids' attribute")

        idle_threshold_minutes = getattr(instance, "idle_threshold_minutes", 60)

        return {
            "instance_ids": instance_ids,  # Keep as list for AWSExecutor
            "idle_threshold_minutes": idle_threshold_minutes,
        }
