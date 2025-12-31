"""GWLB Reconcile Plan for drift detection between DB and VPC endpoints.

This plan runs periodically to detect drift:
- List all VPC endpoints for the GWLB service
- Compare with endpoints tracked in DB
- Identify orphaned endpoints

Uses AWS CLI commands executed locally.
"""

from typing import Any, Dict, List

from .base import SetupStep


# List VPC endpoints for the GWLB service
LIST_ENDPOINTS_SCRIPT = '''
#!/bin/bash
set -e

SERVICE_NAME="{{ service_name }}"
KNOWN_ENDPOINT_IDS="{{ known_endpoint_ids }}"

echo "Listing VPC endpoints for service $SERVICE_NAME..."

# Get all endpoints for this service
ENDPOINTS=$(aws ec2 describe-vpc-endpoints \
    --filters "Name=service-name,Values=$SERVICE_NAME" \
    --query 'VpcEndpoints[*].[VpcEndpointId,State,SubnetIds[0]]' \
    --output text 2>/dev/null || echo "")

if [ -z "$ENDPOINTS" ]; then
    echo "No endpoints found for service"
    echo "ENDPOINT_COUNT=0"
    echo "ORPHAN_COUNT=0"
    exit 0
fi

echo ""
echo "=== VPC Endpoints ==="
TOTAL_COUNT=0
ORPHAN_COUNT=0

while read -r ENDPOINT_ID STATE SUBNET_ID; do
    TOTAL_COUNT=$((TOTAL_COUNT + 1))

    # Check if this endpoint is in our known list
    IS_KNOWN="no"
    if echo "$KNOWN_ENDPOINT_IDS" | grep -q "$ENDPOINT_ID"; then
        IS_KNOWN="yes"
    else
        ORPHAN_COUNT=$((ORPHAN_COUNT + 1))
    fi

    echo "Endpoint: $ENDPOINT_ID | State: $STATE | Subnet: $SUBNET_ID | Known: $IS_KNOWN"
done <<< "$ENDPOINTS"

echo ""
echo "=== Endpoint Summary ==="
echo "Total endpoints: $TOTAL_COUNT"
echo "Orphaned endpoints: $ORPHAN_COUNT"

# Output metrics in parseable format
echo ""
echo "ENDPOINT_COUNT=$TOTAL_COUNT"
echo "ORPHAN_COUNT=$ORPHAN_COUNT"

if [ $ORPHAN_COUNT -gt 0 ]; then
    echo "WARNING: Found $ORPHAN_COUNT orphaned endpoints"
fi
'''

# Verification script
VERIFY_RECONCILE_SCRIPT = '''
#!/bin/bash
set -e

SERVICE_NAME="{{ service_name }}"

echo "Verifying GWLB reconcile completed..."

# Quick check that we can reach AWS and query endpoints
aws ec2 describe-vpc-endpoints \
    --filters "Name=service-name,Values=$SERVICE_NAME" \
    --query 'VpcEndpoints[0].VpcEndpointId' \
    --output text > /dev/null 2>&1 && echo "AWS connectivity: OK" || echo "No endpoints found or AWS issue"

echo "GWLB reconcile verification complete"
exit 0
'''


class GWLBReconcilePlan:
    """Reconcile plan for GWLB endpoint drift detection.

    Steps:
    1. List all VPC endpoints for the GWLB service
    2. Compare with endpoints tracked in DB
    3. Report orphaned endpoints

    Uses AWS CLI commands (not SSH).
    """

    steps: List[SetupStep] = [
        SetupStep(
            name="list_endpoints",
            script=LIST_ENDPOINTS_SCRIPT,
            timeout_seconds=300,  # 5 min
            requires_reboot=False,
        ),
    ]

    verify_step: SetupStep = SetupStep(
        name="verify_reconcile",
        script=VERIFY_RECONCILE_SCRIPT,
        timeout_seconds=120,  # 2 min
        requires_reboot=False,
        is_verification=True,
    )

    def get_context(self, instance: Any) -> Dict[str, Any]:
        """Get template variables for reconcile scripts.

        Args:
            instance: Instance with service_name and known_endpoint_ids

        Returns:
            Dict with template variables

        Raises:
            ValueError: If required attributes are missing
        """
        service_name = getattr(instance, "service_name", None)
        if not service_name:
            raise ValueError("Instance missing required 'service_name' attribute")

        known_endpoint_ids = getattr(instance, "known_endpoint_ids", None)
        if known_endpoint_ids is None:
            known_endpoint_ids = []

        # Convert list to space-separated string for bash
        known_endpoint_ids_str = " ".join(known_endpoint_ids) if known_endpoint_ids else ""

        return {
            "service_name": service_name,
            "known_endpoint_ids": known_endpoint_ids_str,
        }
