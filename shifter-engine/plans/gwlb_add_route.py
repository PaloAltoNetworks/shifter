"""GWLB Add Route Plan for connecting a range to NGFW.

This plan runs when a range needs NGFW inspection:
- Create VPC endpoint in range subnet (GatewayLoadBalancer type)
- Update route table to send 0.0.0.0/0 through the endpoint

Uses AWS CLI commands executed locally.
"""

from typing import Any, Dict, List

from .base import SetupStep


# Create VPC endpoint in range subnet
CREATE_ENDPOINT_SCRIPT = '''
#!/bin/bash
set -e

SERVICE_NAME="{{ service_name }}"
SUBNET_ID="{{ subnet_id }}"
VPC_ID="{{ vpc_id }}"

echo "Creating GWLB endpoint in subnet $SUBNET_ID..."

# Create the VPC endpoint
ENDPOINT_ID=$(aws ec2 create-vpc-endpoint \
    --vpc-endpoint-type GatewayLoadBalancer \
    --service-name "$SERVICE_NAME" \
    --vpc-id "$VPC_ID" \
    --subnet-ids "$SUBNET_ID" \
    --query 'VpcEndpoint.VpcEndpointId' \
    --output text)

echo "Created endpoint: $ENDPOINT_ID"

# Wait for endpoint to be available
echo "Waiting for endpoint to be available..."
MAX_ATTEMPTS=30
ATTEMPT=0

while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    STATE=$(aws ec2 describe-vpc-endpoints \
        --vpc-endpoint-ids "$ENDPOINT_ID" \
        --query 'VpcEndpoints[0].State' \
        --output text 2>/dev/null || echo "unknown")

    echo "Attempt $((ATTEMPT + 1))/$MAX_ATTEMPTS - State: $STATE"

    if [ "$STATE" = "available" ]; then
        echo "Endpoint is available"
        echo "ENDPOINT_ID=$ENDPOINT_ID"
        exit 0
    fi

    if [ "$STATE" = "failed" ]; then
        echo "ERROR: Endpoint creation failed"
        exit 1
    fi

    ATTEMPT=$((ATTEMPT + 1))
    sleep 10
done

echo "ERROR: Endpoint did not become available within 5 minutes"
exit 1
'''

# Update route table with default route through endpoint
ADD_ROUTE_SCRIPT = '''
#!/bin/bash
set -e

ROUTE_TABLE_ID="{{ route_table_id }}"
ENDPOINT_ID="{{ endpoint_id }}"

echo "Adding default route through endpoint $ENDPOINT_ID to route table $ROUTE_TABLE_ID..."

# First, try to delete any existing default route (may not exist)
aws ec2 delete-route \
    --route-table-id "$ROUTE_TABLE_ID" \
    --destination-cidr-block "0.0.0.0/0" 2>/dev/null || true

# Create the new route through the GWLB endpoint
aws ec2 create-route \
    --route-table-id "$ROUTE_TABLE_ID" \
    --destination-cidr-block "0.0.0.0/0" \
    --vpc-endpoint-id "$ENDPOINT_ID"

echo "Route added successfully"
'''

# Verification script
VERIFY_ROUTE_SCRIPT = '''
#!/bin/bash
set -e

ROUTE_TABLE_ID="{{ route_table_id }}"
ENDPOINT_ID="{{ endpoint_id }}"

echo "Verifying route configuration..."

# Check if route exists
ROUTE=$(aws ec2 describe-route-tables \
    --route-table-ids "$ROUTE_TABLE_ID" \
    --query "RouteTables[0].Routes[?DestinationCidrBlock=='0.0.0.0/0']" \
    --output text 2>/dev/null || echo "")

if echo "$ROUTE" | grep -q "$ENDPOINT_ID"; then
    echo "Route verification: OK"
    echo "Default route points to endpoint $ENDPOINT_ID"
    exit 0
else
    echo "WARNING: Default route may not be configured correctly"
    echo "Route details: $ROUTE"
    exit 0
fi
'''


class GWLBAddRoutePlan:
    """Add route plan for GWLB endpoint creation.

    Steps:
    1. Create VPC endpoint in range subnet (GatewayLoadBalancer type)
    2. Update route table to send 0.0.0.0/0 through endpoint

    Uses AWS CLI commands (not SSH).
    """

    steps: List[SetupStep] = [
        SetupStep(
            name="create_endpoint",
            script=CREATE_ENDPOINT_SCRIPT,
            timeout_seconds=360,  # 6 min - endpoint creation can take time
            requires_reboot=False,
        ),
        SetupStep(
            name="add_route",
            script=ADD_ROUTE_SCRIPT,
            timeout_seconds=120,  # 2 min
            requires_reboot=False,
        ),
    ]

    verify_step: SetupStep = SetupStep(
        name="verify_route",
        script=VERIFY_ROUTE_SCRIPT,
        timeout_seconds=120,  # 2 min
        requires_reboot=False,
        is_verification=True,
    )

    def get_context(self, instance: Any) -> Dict[str, Any]:
        """Get template variables for add route scripts.

        Args:
            instance: Instance with service_name, subnet_id, route_table_id, vpc_id

        Returns:
            Dict with template variables

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

        # endpoint_id is set dynamically after create_endpoint step
        endpoint_id = getattr(instance, "endpoint_id", "")

        return {
            "service_name": service_name,
            "subnet_id": subnet_id,
            "route_table_id": route_table_id,
            "vpc_id": vpc_id,
            "endpoint_id": endpoint_id,
        }
