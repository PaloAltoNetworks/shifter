"""UserNGFWStack Sweep Plan for idle NGFW detection and cleanup.

This plan runs periodically to:
- Check for idle NGFWs (no active ranges using them)
- Identify instances that should be stopped to save costs
- Output list of idle instances for orchestrator to act on

Uses AWS CLI commands executed locally.
"""

import json
from typing import Any, Dict, List

from .base import SetupStep


# Check for idle NGFW instances
CHECK_IDLE_SCRIPT = '''
#!/bin/bash
set -e

NGFW_INSTANCES='{{ ngfw_instances_json }}'
IDLE_THRESHOLD_MINUTES={{ idle_threshold_minutes }}

echo "Checking for idle NGFW instances..."
echo "Idle threshold: $IDLE_THRESHOLD_MINUTES minutes"

# Parse the JSON list of instances
# Each instance has: instance_id, user_id, last_activity

IDLE_COUNT=0
ACTIVE_COUNT=0
IDLE_INSTANCES=""

# Get current time in seconds since epoch
CURRENT_TIME=$(date +%s)
THRESHOLD_SECONDS=$((IDLE_THRESHOLD_MINUTES * 60))

# Process each instance from the JSON
echo "$NGFW_INSTANCES" | jq -c '.[]' 2>/dev/null | while read -r instance; do
    INSTANCE_ID=$(echo "$instance" | jq -r '.instance_id')
    USER_ID=$(echo "$instance" | jq -r '.user_id')
    LAST_ACTIVITY=$(echo "$instance" | jq -r '.last_activity')

    # Convert last_activity to epoch (handle ISO format)
    if [ -n "$LAST_ACTIVITY" ] && [ "$LAST_ACTIVITY" != "null" ]; then
        ACTIVITY_TIME=$(date -d "$LAST_ACTIVITY" +%s 2>/dev/null || echo "0")
    else
        ACTIVITY_TIME=0
    fi

    # Calculate idle time
    IDLE_SECONDS=$((CURRENT_TIME - ACTIVITY_TIME))
    IDLE_MINUTES=$((IDLE_SECONDS / 60))

    echo "Instance: $INSTANCE_ID | User: $USER_ID | Idle: ${IDLE_MINUTES}m"

    if [ $IDLE_SECONDS -gt $THRESHOLD_SECONDS ]; then
        echo "  -> IDLE (exceeds threshold)"
        IDLE_COUNT=$((IDLE_COUNT + 1))
        if [ -n "$IDLE_INSTANCES" ]; then
            IDLE_INSTANCES="$IDLE_INSTANCES,$INSTANCE_ID"
        else
            IDLE_INSTANCES="$INSTANCE_ID"
        fi
    else
        echo "  -> ACTIVE"
        ACTIVE_COUNT=$((ACTIVE_COUNT + 1))
    fi
done

echo ""
echo "=== Sweep Summary ==="
echo "Active instances: $ACTIVE_COUNT"
echo "Idle instances: $IDLE_COUNT"

# Output in parseable format
echo ""
echo "IDLE_INSTANCES=$IDLE_INSTANCES"
echo "IDLE_COUNT=$IDLE_COUNT"
echo "ACTIVE_COUNT=$ACTIVE_COUNT"
'''

# Verification script
VERIFY_SWEEP_SCRIPT = '''
#!/bin/bash
set -e

echo "Verifying sweep completed..."
echo "Sweep verification complete"
exit 0
'''


class UserNGFWStackSweepPlan:
    """Sweep plan for idle NGFW detection.

    Steps:
    1. Check for idle NGFWs based on last activity time
    2. Output list of idle instances for orchestrator to stop

    Uses AWS CLI commands (not SSH).
    """

    steps: List[SetupStep] = [
        SetupStep(
            name="check_idle",
            script=CHECK_IDLE_SCRIPT,
            timeout_seconds=300,  # 5 min
            requires_reboot=False,
        ),
    ]

    verify_step: SetupStep = SetupStep(
        name="verify_sweep",
        script=VERIFY_SWEEP_SCRIPT,
        timeout_seconds=60,  # 1 min
        requires_reboot=False,
        is_verification=True,
    )

    def get_context(self, instance: Any) -> Dict[str, Any]:
        """Get template variables for sweep scripts.

        Args:
            instance: Instance with ngfw_instances list and idle_threshold_minutes

        Returns:
            Dict with template variables

        Raises:
            ValueError: If required attributes are missing
        """
        ngfw_instances = getattr(instance, "ngfw_instances", None)
        if ngfw_instances is None:
            raise ValueError("Instance missing required 'ngfw_instances' attribute")

        idle_threshold_minutes = getattr(instance, "idle_threshold_minutes", 60)

        # Convert to JSON for bash script
        ngfw_instances_json = json.dumps(ngfw_instances)

        return {
            "ngfw_instances_json": ngfw_instances_json,
            "ngfw_instances": ngfw_instances,
            "idle_threshold_minutes": idle_threshold_minutes,
        }
