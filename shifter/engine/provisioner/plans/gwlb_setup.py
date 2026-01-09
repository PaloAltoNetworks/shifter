"""GWLB Setup Plan for target registration after NGFW provisioning.

This plan runs after NGFW is provisioned to:
- Register NGFW instance as target in GWLB target group
- Wait for target to become healthy

Uses AWSExecutor methods for AWS API calls (not bash scripts).
"""

from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass
class GWLBSetupStep:
    """A step in the GWLB setup plan that uses AWSExecutor.

    Attributes:
        name: Unique identifier for this step.
        action: AWSExecutor method name to call.
        params: List of context keys to pass as method parameters.
    """

    name: str
    action: str
    params: list[str] = field(default_factory=list)


class GWLBSetupPlan:
    """Setup plan for GWLB target registration.

    Steps:
    1. Register NGFW instance in GWLB target group
    2. Wait for target to become healthy

    Uses AWSExecutor methods for AWS API calls.
    """

    name: ClassVar[str] = "gwlb_setup"

    steps: ClassVar[list[GWLBSetupStep]] = [
        GWLBSetupStep(
            name="register_target",
            action="register_target",
            params=["target_group_arn", "target_id"],
        ),
        GWLBSetupStep(
            name="wait_for_healthy",
            action="wait_for_target_healthy",
            params=["target_group_arn", "target_id"],
        ),
    ]

    def get_context(self, instance: Any) -> dict[str, Any]:
        """Get context variables for GWLB setup.

        Args:
            instance: Instance with target_group_arn and instance_id attributes

        Returns:
            Dict with context variables for AWSExecutor methods

        Raises:
            ValueError: If required attributes are missing
        """
        target_group_arn = getattr(instance, "target_group_arn", None)
        if not target_group_arn:
            raise ValueError(
                "Instance missing required 'target_group_arn' attribute"
            )

        # Use instance_id for target registration
        # (target_type="instance" in target group)
        instance_id = getattr(instance, "instance_id", None)
        if not instance_id:
            raise ValueError(
                "Instance missing 'instance_id' - required for target registration"
            )

        return {
            "target_group_arn": target_group_arn,
            "target_id": instance_id,
        }
