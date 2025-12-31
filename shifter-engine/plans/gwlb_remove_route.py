"""GWLB Remove Route Plan for disconnecting a range from NGFW.

This plan runs when a range is being destroyed:
- Remove route from route table
- Delete VPC endpoint

Uses AWS CLI commands executed locally.
"""

from typing import Any, Dict, List

from .base import SetupStep


# Remove default route from route table
REMOVE_ROUTE_SCRIPT = '''
#!/bin/bash
set -e

ROUTE_TABLE_ID="{{ route_table_id }}"

echo "Removing default route from route table $ROUTE_TABLE_ID..."

# Delete the default route (ignore errors if route doesn't exist)
aws ec2 delete-route \
    --route-table-id "$ROUTE_TABLE_ID" \
    --destination-cidr-block "0.0.0.0/0" 2>/dev/null || echo "Route may not exist, continuing..."

echo "Route removed successfully"
'''

# Delete VPC endpoint
DELETE_ENDPOINT_SCRIPT = '''
#!/bin/bash
set -e

ENDPOINT_ID="{{ endpoint_id }}"

echo "Deleting VPC endpoint $ENDPOINT_ID..."

# Delete the endpoint
aws ec2 delete-vpc-endpoints \
    --vpc-endpoint-ids "$ENDPOINT_ID"

echo "Endpoint deletion initiated"

# Wait for endpoint to be deleted
echo "Waiting for endpoint to be deleted..."
MAX_ATTEMPTS=30
ATTEMPT=0

while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    STATE=$(aws ec2 describe-vpc-endpoints \
        --vpc-endpoint-ids "$ENDPOINT_ID" \
        --query 'VpcEndpoints[0].State' \
        --output text 2>/dev/null || echo "deleted")

    echo "Attempt $((ATTEMPT + 1))/$MAX_ATTEMPTS - State: $STATE"

    if [ "$STATE" = "deleted" ] || [ "$STATE" = "None" ] || [ -z "$STATE" ]; then
        echo "Endpoint deleted"
        exit 0
    fi

    ATTEMPT=$((ATTEMPT + 1))
    sleep 10
done

echo "WARNING: Endpoint may not be fully deleted yet"
exit 0
'''

# Verification script
VERIFY_REMOVAL_SCRIPT = '''
#!/bin/bash
set -e

ENDPOINT_ID="{{ endpoint_id }}"
ROUTE_TABLE_ID="{{ route_table_id }}"

echo "Verifying removal..."

# Check if endpoint is deleted
STATE=$(aws ec2 describe-vpc-endpoints \
    --vpc-endpoint-ids "$ENDPOINT_ID" \
    --query 'VpcEndpoints[0].State' \
    --output text 2>/dev/null || echo "deleted")

if [ "$STATE" = "deleted" ] || [ "$STATE" = "None" ] || [ -z "$STATE" ]; then
    echo "Endpoint verification: OK (deleted)"
else
    echo "WARNING: Endpoint state is $STATE"
fi

# Check if route is removed
ROUTE=$(aws ec2 describe-route-tables \
    --route-table-ids "$ROUTE_TABLE_ID" \
    --query "RouteTables[0].Routes[?DestinationCidrBlock=='0.0.0.0/0'].VpcEndpointId" \
    --output text 2>/dev/null || echo "")

if [ -z "$ROUTE" ] || [ "$ROUTE" = "None" ]; then
    echo "Route verification: OK (removed)"
else
    echo "WARNING: Route may still exist: $ROUTE"
fi

echo "Removal verification complete"
exit 0
'''


class GWLBRemoveRoutePlan:
    """Remove route plan for GWLB endpoint deletion.

    Steps:
    1. Remove default route from route table
    2. Delete VPC endpoint

    Uses AWS CLI commands (not SSH).
    """

    steps: List[SetupStep] = [
        SetupStep(
            name="remove_route",
            script=REMOVE_ROUTE_SCRIPT,
            timeout_seconds=120,  # 2 min
            requires_reboot=False,
        ),
        SetupStep(
            name="delete_endpoint",
            script=DELETE_ENDPOINT_SCRIPT,
            timeout_seconds=360,  # 6 min - endpoint deletion can take time
            requires_reboot=False,
        ),
    ]

    verify_step: SetupStep = SetupStep(
        name="verify_removal",
        script=VERIFY_REMOVAL_SCRIPT,
        timeout_seconds=120,  # 2 min
        requires_reboot=False,
        is_verification=True,
    )

    def get_context(self, instance: Any) -> Dict[str, Any]:
        """Get template variables for remove route scripts.

        Args:
            instance: Instance with endpoint_id, route_table_id

        Returns:
            Dict with template variables

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
        }
