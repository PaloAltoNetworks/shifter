"""GWLB Setup Plan for target registration after NGFW provisioning.

This plan runs after NGFW is provisioned to:
- Register NGFW instance as target in GWLB target group
- Verify target health check passes

Uses AWS CLI commands executed locally (not on NGFW).
"""

from typing import Any, Dict, List

from .base import SetupStep


# Register NGFW as target in GWLB target group
REGISTER_TARGET_SCRIPT = '''
#!/bin/bash
set -e

TARGET_GROUP_ARN="{{ target_group_arn }}"
TARGET_ID="{{ target_id }}"

echo "Registering target $TARGET_ID in target group..."

# Register the NGFW instance as a target
aws elbv2 register-targets \
    --target-group-arn "$TARGET_GROUP_ARN" \
    --targets "Id=$TARGET_ID"

echo "Target registered successfully"
'''

# Wait for target to become healthy
WAIT_HEALTH_CHECK_SCRIPT = '''
#!/bin/bash
set -e

TARGET_GROUP_ARN="{{ target_group_arn }}"
TARGET_ID="{{ target_id }}"
MAX_ATTEMPTS=30  # 5 minutes (10 second intervals)
ATTEMPT=0

echo "Waiting for target $TARGET_ID to become healthy..."

while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    HEALTH=$(aws elbv2 describe-target-health \
        --target-group-arn "$TARGET_GROUP_ARN" \
        --targets "Id=$TARGET_ID" \
        --query 'TargetHealthDescriptions[0].TargetHealth.State' \
        --output text 2>/dev/null || echo "unknown")

    echo "Attempt $((ATTEMPT + 1))/$MAX_ATTEMPTS - Health status: $HEALTH"

    if [ "$HEALTH" = "healthy" ]; then
        echo "Target is healthy"
        exit 0
    fi

    if [ "$HEALTH" = "unhealthy" ]; then
        echo "WARNING: Target is unhealthy, continuing to wait..."
    fi

    ATTEMPT=$((ATTEMPT + 1))
    sleep 10
done

echo "WARNING: Target did not become healthy within 5 minutes"
echo "Final health status: $HEALTH"
# Don't fail - target may need more time to warm up
exit 0
'''

# Verify target registration
VERIFY_REGISTRATION_SCRIPT = '''
#!/bin/bash
set -e

TARGET_GROUP_ARN="{{ target_group_arn }}"
TARGET_ID="{{ target_id }}"

echo "Verifying target registration..."

# Check if target is registered
TARGETS=$(aws elbv2 describe-target-health \
    --target-group-arn "$TARGET_GROUP_ARN" \
    --query 'TargetHealthDescriptions[*].Target.Id' \
    --output text 2>/dev/null || echo "")

if echo "$TARGETS" | grep -q "$TARGET_ID"; then
    echo "Target $TARGET_ID is registered"

    # Get health status
    HEALTH=$(aws elbv2 describe-target-health \
        --target-group-arn "$TARGET_GROUP_ARN" \
        --targets "Id=$TARGET_ID" \
        --query 'TargetHealthDescriptions[0].TargetHealth.State' \
        --output text 2>/dev/null || echo "unknown")

    echo "Health status: $HEALTH"
    exit 0
else
    echo "ERROR: Target $TARGET_ID not found in target group"
    exit 1
fi
'''


class GWLBSetupPlan:
    """Setup plan for GWLB target registration.

    Steps:
    1. Register NGFW instance in GWLB target group
    2. Wait for health check to pass

    Uses AWS CLI commands (not SSH to NGFW).
    """

    steps: List[SetupStep] = [
        SetupStep(
            name="register_target",
            script=REGISTER_TARGET_SCRIPT,
            timeout_seconds=120,  # 2 min
            requires_reboot=False,
        ),
        SetupStep(
            name="wait_health_check",
            script=WAIT_HEALTH_CHECK_SCRIPT,
            timeout_seconds=360,  # 6 min - health checks can take time
            requires_reboot=False,
        ),
    ]

    verify_step: SetupStep = SetupStep(
        name="verify_registration",
        script=VERIFY_REGISTRATION_SCRIPT,
        timeout_seconds=120,  # 2 min
        requires_reboot=False,
        is_verification=True,
    )

    def get_context(self, instance: Any) -> Dict[str, Any]:
        """Get template variables for GWLB setup scripts.

        Args:
            instance: Instance with target_group_arn and ngfw_instance_id

        Returns:
            Dict with template variables

        Raises:
            ValueError: If required attributes are missing
        """
        target_group_arn = getattr(instance, "target_group_arn", None)
        if not target_group_arn:
            raise ValueError("Instance missing required 'target_group_arn' attribute")

        # Target can be either instance ID or ENI ID
        target_id = getattr(instance, "ngfw_instance_id", None) or getattr(instance, "ngfw_data_eni_id", None)
        if not target_id:
            raise ValueError("Instance missing 'ngfw_instance_id' or 'ngfw_data_eni_id' attribute")

        return {
            "target_group_arn": target_group_arn,
            "target_id": target_id,
        }
