"""GWLB Remove Route Plan for disconnecting a range from NGFW.

This plan runs when a range is being destroyed:
- Delete route from route table
- Delete VPC endpoint

Uses AWSExecutor methods for AWS API calls (not bash scripts).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class GWLBRemoveRouteStep:
    """A step in the GWLB remove route plan that uses AWSExecutor.

    Attributes:
        name: Unique identifier for this step.
        action: AWSExecutor method name to call.
        params: List of context keys to pass as method parameters.
    """

    name: str
    action: str
    params: List[str] = field(default_factory=list)


class GWLBRemoveRoutePlan:
    """Remove route plan for GWLB endpoint deletion.

    Steps:
    1. Delete route from route table (must be before endpoint deletion)
    2. Delete VPC endpoint

    Uses AWSExecutor methods for AWS API calls.
    """

    name: str = "gwlb_remove_route"

    steps: List[GWLBRemoveRouteStep] = [
        GWLBRemoveRouteStep(
            name="delete_route",
            action="delete_route",
            params=["route_table_id", "destination"],
        ),
        GWLBRemoveRouteStep(
            name="delete_endpoint",
            action="delete_endpoint",
            params=["endpoint_id"],
        ),
    ]

    def get_context(self, instance: Any) -> Dict[str, Any]:
        """Get context variables for GWLB remove route.

        Args:
            instance: Instance with endpoint_id, route_table_id

        Returns:
            Dict with context variables for AWSExecutor methods

        Raises:
            ValueError: If required attributes are missing
        """
        endpoint_id = getattr(instance, "endpoint_id", None)
        if not endpoint_id:
            raise ValueError("Instance missing required 'endpoint_id' attribute")

        route_table_id = getattr(instance, "route_table_id", None)
        if not route_table_id:
            raise ValueError("Instance missing required 'route_table_id' attribute")

        return {
            "endpoint_id": endpoint_id,
            "route_table_id": route_table_id,
            "destination": "0.0.0.0/0",  # Default route
        }
