"""NGFW Stop Plan for stopping a running NGFW instance.

This plan runs to stop a running NGFW:
- Stop EC2 instance
- Wait for stopped state

Uses AWS CLI commands executed locally (not on NGFW).
"""

from typing import Any, Dict, List

from .base import SetupStep


# Stop EC2 instance script
STOP_INSTANCE_SCRIPT = '''
#!/bin/bash
set -e

INSTANCE_ID="{{ instance_id }}"

echo "Stopping NGFW instance $INSTANCE_ID..."

# Stop the EC2 instance
aws ec2 stop-instances --instance-ids "$INSTANCE_ID"

echo "Stop command sent successfully"
'''

# Wait for instance to be stopped
WAIT_STOPPED_SCRIPT = '''
#!/bin/bash
set -e

INSTANCE_ID="{{ instance_id }}"
MAX_ATTEMPTS=30  # 5 minutes (10 second intervals)
ATTEMPT=0

echo "Waiting for instance $INSTANCE_ID to be stopped..."

while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    STATE=$(aws ec2 describe-instances \
        --instance-ids "$INSTANCE_ID" \
        --query 'Reservations[0].Instances[0].State.Name' \
        --output text 2>/dev/null || echo "unknown")

    echo "Attempt $((ATTEMPT + 1))/$MAX_ATTEMPTS - State: $STATE"

    if [ "$STATE" = "stopped" ]; then
        echo "Instance is stopped"
        exit 0
    fi

    ATTEMPT=$((ATTEMPT + 1))
    sleep 10
done

echo "ERROR: Instance did not reach stopped state within 5 minutes"
exit 1
'''

# Verification script
VERIFY_STOPPED_SCRIPT = '''
#!/bin/bash
set -e

INSTANCE_ID="{{ instance_id }}"

echo "Verifying NGFW instance $INSTANCE_ID is stopped..."

# Check EC2 state
STATE=$(aws ec2 describe-instances \
    --instance-ids "$INSTANCE_ID" \
    --query 'Reservations[0].Instances[0].State.Name' \
    --output text 2>/dev/null || echo "unknown")

if [ "$STATE" != "stopped" ]; then
    echo "ERROR: Instance state is $STATE, expected stopped"
    exit 1
fi

echo "EC2 state: stopped"
echo "Verification complete"
exit 0
'''


class NGFWStopPlan:
    """Stop plan for NGFW instance.

    Steps:
    1. Stop EC2 instance
    2. Wait for stopped state

    Uses AWS CLI commands (not SSH to NGFW).
    """

    steps: List[SetupStep] = [
        SetupStep(
            name="stop_instance",
            script=STOP_INSTANCE_SCRIPT,
            timeout_seconds=120,  # 2 min
            requires_reboot=False,
        ),
        SetupStep(
            name="wait_stopped",
            script=WAIT_STOPPED_SCRIPT,
            timeout_seconds=300,  # 5 min
            requires_reboot=False,
        ),
    ]

    verify_step: SetupStep = SetupStep(
        name="verify_stopped",
        script=VERIFY_STOPPED_SCRIPT,
        timeout_seconds=120,  # 2 min
        requires_reboot=False,
        is_verification=True,
    )

    def get_context(self, instance: Any) -> Dict[str, Any]:
        """Get template variables for stop scripts.

        Args:
            instance: Instance with instance_id

        Returns:
            Dict with template variables

        Raises:
            ValueError: If required attributes are missing
        """
        instance_id = getattr(instance, "instance_id", None)
        if not instance_id:
            raise ValueError("Instance missing required 'instance_id' attribute")

        return {
            "instance_id": instance_id,
        }
