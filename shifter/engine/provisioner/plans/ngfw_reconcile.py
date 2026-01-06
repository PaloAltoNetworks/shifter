"""NGFW Reconcile Plan for drift detection between DB and EC2.

This plan runs periodically to detect drift:
- Describe instances via AWSExecutor.describe_instances()
- Compare DB state vs actual EC2 state
- Return instance states for drift analysis

Uses AWSExecutor methods for AWS API calls (not bash scripts).
"""

from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass
class NGFWReconcileStep:
    """A step in the NGFW reconcile plan that uses AWSExecutor.

    Attributes:
        name: Unique identifier for this step.
        action: AWSExecutor method name to call.
        params: List of context keys to pass as method parameters.
    """

    name: str
    action: str
    params: list[str] = field(default_factory=list)


class NGFWReconcilePlan:
    """Reconcile plan for NGFW drift detection.

    Steps:
    1. Describe instances to get current EC2 states

    Uses AWSExecutor methods for AWS API calls.
    """

    name: ClassVar[str] = "ngfw_reconcile"

    steps: ClassVar[list[NGFWReconcileStep]] = [
        NGFWReconcileStep(
            name="describe_instances",
            action="describe_instances",
            params=["instance_ids"],
        ),
    ]

    def get_context(self, instance: Any) -> dict[str, Any]:
        """Get context variables for NGFW reconcile.

        Args:
            instance: Instance with instance_ids list

        Returns:
            Dict with context variables for AWSExecutor methods

        Raises:
            ValueError: If required attributes are missing
        """
        instance_ids = getattr(instance, "instance_ids", None)
        if instance_ids is None:
            raise ValueError("Instance missing required 'instance_ids' attribute")

        return {
            "instance_ids": instance_ids,  # Keep as list for AWSExecutor
        }
