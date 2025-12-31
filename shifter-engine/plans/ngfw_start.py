"""NGFW Start Plan for starting a stopped NGFW instance.

This plan runs to start a stopped NGFW:
- Start EC2 instance
- Wait for running state
- Wait for SSH availability (~3 min for warm start)

Uses AWS CLI commands executed locally (not on NGFW).
"""

from typing import Any, Dict, List

from .base import SetupStep


# Start EC2 instance script
START_INSTANCE_SCRIPT = '''
#!/bin/bash
set -e

INSTANCE_ID="{{ instance_id }}"

echo "Starting NGFW instance $INSTANCE_ID..."

# Start the EC2 instance
aws ec2 start-instances --instance-ids "$INSTANCE_ID"

echo "Start command sent successfully"
'''

# Wait for instance to be running
WAIT_RUNNING_SCRIPT = '''
#!/bin/bash
set -e

INSTANCE_ID="{{ instance_id }}"
MAX_ATTEMPTS=30  # 5 minutes (10 second intervals)
ATTEMPT=0

echo "Waiting for instance $INSTANCE_ID to be running..."

while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    STATE=$(aws ec2 describe-instances \
        --instance-ids "$INSTANCE_ID" \
        --query 'Reservations[0].Instances[0].State.Name' \
        --output text 2>/dev/null || echo "unknown")

    echo "Attempt $((ATTEMPT + 1))/$MAX_ATTEMPTS - State: $STATE"

    if [ "$STATE" = "running" ]; then
        echo "Instance is running"
        exit 0
    fi

    ATTEMPT=$((ATTEMPT + 1))
    sleep 10
done

echo "ERROR: Instance did not reach running state within 5 minutes"
exit 1
'''

# Wait for SSH availability (warm start ~3 min)
WAIT_SSH_READY_SCRIPT = '''
#!/bin/bash
set -e

NGFW_IP="{{ management_ip }}"
MAX_ATTEMPTS=36  # 6 minutes (10 second intervals) - warm start is ~3 min
ATTEMPT=0

echo "Waiting for NGFW SSH availability at $NGFW_IP..."

while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    if timeout 5 bash -c "echo 'show system info' | ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 admin@$NGFW_IP" 2>/dev/null | grep -q "hostname"; then
        echo "NGFW SSH is ready"
        exit 0
    fi
    ATTEMPT=$((ATTEMPT + 1))
    echo "Attempt $ATTEMPT/$MAX_ATTEMPTS - waiting for SSH..."
    sleep 10
done

echo "ERROR: NGFW SSH not available after 6 minutes"
exit 1
'''

# Verification script
VERIFY_RUNNING_SCRIPT = '''
#!/bin/bash
set -e

INSTANCE_ID="{{ instance_id }}"
NGFW_IP="{{ management_ip }}"

echo "Verifying NGFW instance $INSTANCE_ID is running..."

# Check EC2 state
STATE=$(aws ec2 describe-instances \
    --instance-ids "$INSTANCE_ID" \
    --query 'Reservations[0].Instances[0].State.Name' \
    --output text 2>/dev/null || echo "unknown")

if [ "$STATE" != "running" ]; then
    echo "ERROR: Instance state is $STATE, expected running"
    exit 1
fi

echo "EC2 state: running"

# Check SSH connectivity
if timeout 5 bash -c "echo 'show system info' | ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 admin@$NGFW_IP" 2>/dev/null | grep -q "hostname"; then
    echo "SSH connectivity: OK"
else
    echo "WARNING: SSH not responding"
fi

echo "Verification complete"
exit 0
'''


class NGFWStartPlan:
    """Start plan for NGFW instance.

    Steps:
    1. Start EC2 instance
    2. Wait for running state
    3. Wait for SSH availability (~3 min for warm start)

    Uses AWS CLI commands (not SSH to NGFW until final step).
    """

    steps: List[SetupStep] = [
        SetupStep(
            name="start_instance",
            script=START_INSTANCE_SCRIPT,
            timeout_seconds=120,  # 2 min
            requires_reboot=False,
        ),
        SetupStep(
            name="wait_running",
            script=WAIT_RUNNING_SCRIPT,
            timeout_seconds=300,  # 5 min
            requires_reboot=False,
        ),
        SetupStep(
            name="wait_ssh_ready",
            script=WAIT_SSH_READY_SCRIPT,
            timeout_seconds=360,  # 6 min - warm start is ~3 min
            requires_reboot=False,
        ),
    ]

    verify_step: SetupStep = SetupStep(
        name="verify_running",
        script=VERIFY_RUNNING_SCRIPT,
        timeout_seconds=120,  # 2 min
        requires_reboot=False,
        is_verification=True,
    )

    def get_context(self, instance: Any) -> Dict[str, Any]:
        """Get template variables for start scripts.

        Args:
            instance: Instance with instance_id and management_ip

        Returns:
            Dict with template variables

        Raises:
            ValueError: If required attributes are missing
        """
        instance_id = getattr(instance, "instance_id", None)
        if not instance_id:
            raise ValueError("Instance missing required 'instance_id' attribute")

        management_ip = getattr(instance, "management_ip", None)
        if not management_ip:
            raise ValueError("Instance missing required 'management_ip' attribute")

        return {
            "instance_id": instance_id,
            "management_ip": management_ip,
        }
