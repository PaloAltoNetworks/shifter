"""GWLB Setup Plan for target registration after NGFW provisioning.

This plan runs after NGFW is provisioned to:
- Register NGFW data ENI as target in GWLB target group
- Wait for target to become healthy

Uses AWSExecutor methods for AWS API calls (not bash scripts).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List


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
    params: List[str] = field(default_factory=list)


class GWLBSetupPlan:
    """Setup plan for GWLB target registration.

    Steps:
    1. Register NGFW data ENI in GWLB target group
    2. Wait for target to become healthy

    Uses AWSExecutor methods for AWS API calls.
    """

    name: str = "gwlb_setup"

    steps: List[GWLBSetupStep] = [
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

    def get_context(self, instance: Any) -> Dict[str, Any]:
        """Get context variables for GWLB setup.

        Args:
            instance: Instance with target_group_arn and ngfw_data_eni_id/ngfw_instance_id

        Returns:
            Dict with context variables for AWSExecutor methods

        Raises:
            ValueError: If required attributes are missing
        """
        target_group_arn = getattr(instance, "target_group_arn", None)
        if not target_group_arn:
            raise ValueError("Instance missing required 'target_group_arn' attribute")

        # Prefer data ENI ID over instance ID for GWLB target
        # GWLB targets should use ENI for traffic inspection
        ngfw_data_eni_id = getattr(instance, "ngfw_data_eni_id", None)
        ngfw_instance_id = getattr(instance, "ngfw_instance_id", None)

        if ngfw_data_eni_id:
            target_id = ngfw_data_eni_id
        elif ngfw_instance_id:
            target_id = ngfw_instance_id
        else:
            raise ValueError("Instance missing 'ngfw_data_eni_id' or 'ngfw_instance_id' - target ID required")

        return {
            "target_group_arn": target_group_arn,
            "target_id": target_id,
        }
