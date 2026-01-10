"""GWLB Add Route Plan for connecting a range to NGFW.

This plan runs when a range needs NGFW inspection:
- Create VPC endpoint in range subnet (GatewayLoadBalancer type)
- Wait for endpoint to become available
- Update route table to send 0.0.0.0/0 through the endpoint

Uses AWSExecutor methods for AWS API calls (not bash scripts).
"""

from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass
class GWLBAddRouteStep:
    """A step in the GWLB add route plan that uses AWSExecutor.

    Attributes:
        name: Unique identifier for this step.
        action: AWSExecutor method name to call.
        params: List of context keys to pass as method parameters.
    """

    name: str
    action: str
    params: list[str] = field(default_factory=list)


class GWLBAddRoutePlan:
    """Add route plan for GWLB endpoint creation.

    Steps:
    1. Create VPC endpoint in range subnet (GatewayLoadBalancer type)
    2. Wait for endpoint to become available
    3. Create route through endpoint

    Uses AWSExecutor methods for AWS API calls.
    """

    name: ClassVar[str] = "gwlb_add_route"

    steps: ClassVar[list[GWLBAddRouteStep]] = [
        GWLBAddRouteStep(
            name="create_endpoint",
            action="create_endpoint",
            params=["vpc_id", "service_name", "subnet_ids"],
        ),
        GWLBAddRouteStep(
            name="wait_for_endpoint_available",
            action="wait_for_endpoint_available",
            params=["endpoint_id"],
        ),
        GWLBAddRouteStep(
            name="create_route",
            action="create_route",
            params=["route_table_id", "destination", "endpoint_id"],
        ),
    ]

    def get_context(self, instance: Any) -> dict[str, Any]:
        """Get context variables for GWLB add route.

        Args:
            instance: Instance with service_name, subnet_id, route_table_id, vpc_id

        Returns:
            Dict with context variables for AWSExecutor methods

        Raises:
            ValueError: If required attributes are missing
        """
        service_name = getattr(instance, "service_name", None)
        if not service_name:
            raise ValueError("Instance missing required 'service_name' attribute")

        subnet_id = getattr(instance, "subnet_id", None)
        if not subnet_id:
            raise ValueError("Instance missing required 'subnet_id' attribute")

        route_table_id = getattr(instance, "route_table_id", None)
        if not route_table_id:
            raise ValueError("Instance missing required 'route_table_id' attribute")

        vpc_id = getattr(instance, "vpc_id", None)
        if not vpc_id:
            raise ValueError("Instance missing required 'vpc_id' attribute")

        return {
            "service_name": service_name,
            "subnet_ids": [subnet_id],  # AWSExecutor expects list
            "route_table_id": route_table_id,
            "vpc_id": vpc_id,
            "destination": "0.0.0.0/0",  # Default route
            "endpoint_id": getattr(instance, "endpoint_id", ""),  # Set after create_endpoint
        }
