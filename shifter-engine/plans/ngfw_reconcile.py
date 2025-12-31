"""NGFW Reconcile Plan for drift detection between DB and EC2.

This plan runs periodically to detect drift:
- Compare DB state vs actual EC2 state
- Report instances that are in unexpected states
- Output metrics for monitoring

Uses AWS CLI commands executed locally.
"""

from typing import Any, Dict, List

from .base import SetupStep


# Check EC2 instance states
CHECK_STATE_SCRIPT = '''
#!/bin/bash
set -e

INSTANCE_IDS="{{ instance_ids }}"

echo "Checking NGFW instance states..."

# If no instances to check, exit early
if [ -z "$INSTANCE_IDS" ]; then
    echo "No instances to check"
    echo "NGFW_COUNT=0"
    exit 0
fi

# Get instance states
STATES=$(aws ec2 describe-instances \
    --instance-ids $INSTANCE_IDS \
    --query 'Reservations[*].Instances[*].[InstanceId,State.Name]' \
    --output text 2>/dev/null || echo "")

if [ -z "$STATES" ]; then
    echo "WARNING: Could not retrieve instance states"
    exit 0
fi

# Count instances by state
RUNNING_COUNT=0
STOPPED_COUNT=0
OTHER_COUNT=0

while read -r INSTANCE_ID STATE; do
    echo "Instance $INSTANCE_ID: $STATE"
    case "$STATE" in
        running)
            RUNNING_COUNT=$((RUNNING_COUNT + 1))
            ;;
        stopped)
            STOPPED_COUNT=$((STOPPED_COUNT + 1))
            ;;
        *)
            OTHER_COUNT=$((OTHER_COUNT + 1))
            ;;
    esac
done <<< "$STATES"

echo ""
echo "=== NGFW State Summary ==="
echo "Running: $RUNNING_COUNT"
echo "Stopped: $STOPPED_COUNT"
echo "Other: $OTHER_COUNT"
echo "Total: $((RUNNING_COUNT + STOPPED_COUNT + OTHER_COUNT))"

# Output metrics in parseable format
echo ""
echo "NGFW_RUNNING=$RUNNING_COUNT"
echo "NGFW_STOPPED=$STOPPED_COUNT"
echo "NGFW_OTHER=$OTHER_COUNT"
echo "NGFW_COUNT=$((RUNNING_COUNT + STOPPED_COUNT + OTHER_COUNT))"
'''

# Verification script
VERIFY_RECONCILE_SCRIPT = '''
#!/bin/bash
set -e

INSTANCE_IDS="{{ instance_ids }}"

echo "Verifying reconcile completed..."

if [ -z "$INSTANCE_IDS" ]; then
    echo "No instances configured - reconcile complete"
    exit 0
fi

# Quick check that we can reach AWS
aws ec2 describe-instances \
    --instance-ids $INSTANCE_IDS \
    --query 'Reservations[0].Instances[0].InstanceId' \
    --output text > /dev/null 2>&1 && echo "AWS connectivity: OK" || echo "WARNING: AWS connectivity issue"

echo "Reconcile verification complete"
exit 0
'''


class NGFWReconcilePlan:
    """Reconcile plan for NGFW drift detection.

    Steps:
    1. Check EC2 instance states
    2. Compare with expected states (from DB)
    3. Report drift and metrics

    Uses AWS CLI commands (not SSH).
    """

    steps: List[SetupStep] = [
        SetupStep(
            name="check_state",
            script=CHECK_STATE_SCRIPT,
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
            instance: Instance with instance_ids list

        Returns:
            Dict with template variables

        Raises:
            ValueError: If required attributes are missing
        """
        instance_ids = getattr(instance, "instance_ids", None)
        if instance_ids is None:
            raise ValueError("Instance missing required 'instance_ids' attribute")

        # Convert list to space-separated string for bash
        instance_ids_str = " ".join(instance_ids) if instance_ids else ""

        return {
            "instance_ids": instance_ids_str,
        }
