"""GWLB Reconcile Plan for drift detection between DB and VPC endpoints.

This plan runs periodically to detect drift:
- Describe endpoints via AWSExecutor.describe_endpoints()
- Compare DB endpoints vs actual VPC endpoints
- Identify orphaned endpoints for cleanup

Uses AWSExecutor methods for AWS API calls (not bash scripts).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class GWLBReconcileStep:
    """A step in the GWLB reconcile plan that uses AWSExecutor.

    Attributes:
        name: Unique identifier for this step.
        action: AWSExecutor method name to call.
        params: List of context keys to pass as method parameters.
    """

    name: str
    action: str
    params: List[str] = field(default_factory=list)


class GWLBReconcilePlan:
    """Reconcile plan for GWLB endpoint drift detection.

    Steps:
    1. Describe endpoints filtered by service name

    Uses AWSExecutor methods for AWS API calls.
    """

    name: str = "gwlb_reconcile"

    steps: List[GWLBReconcileStep] = [
        GWLBReconcileStep(
            name="describe_endpoints",
            action="describe_endpoints",
            params=["service_name"],
        ),
    ]

    def get_context(self, instance: Any) -> Dict[str, Any]:
        """Get context variables for GWLB reconcile.

        Args:
            instance: Instance with service_name and known_endpoint_ids

        Returns:
            Dict with context variables for AWSExecutor methods

        Raises:
            ValueError: If required attributes are missing
        """
        service_name = getattr(instance, "service_name", None)
        if not service_name:
            raise ValueError("Instance missing required 'service_name' attribute")

        known_endpoint_ids = getattr(instance, "known_endpoint_ids", None)
        if known_endpoint_ids is None:
            known_endpoint_ids = []

        return {
            "service_name": service_name,
            "known_endpoint_ids": known_endpoint_ids,  # Keep as list for comparison
        }
