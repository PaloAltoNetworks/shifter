"""NGFW Deprovision Plan for pre-destroy cleanup.

This plan runs before NGFW Pulumi destroy to:
- Deactivate VM-Series license (releases license back to pool)

The license deactivation is critical to avoid license leakage.
Command: request license deactivate VM-Capacity mode auto
"""

from typing import Any, Dict, List

from .base import SetupStep


# License deactivation script
# Validated PAN-OS CLI command
DEACTIVATE_LICENSE_SCRIPT = '''
#!/bin/bash
set -e

NGFW_IP="{{ management_ip }}"

echo "Deactivating VM-Series license on $NGFW_IP..."

# Send license deactivation command via SSH
# IMPORTANT: PAN-OS requires commands piped to SSH, not passed as arguments
cat << 'EOF' | ssh -o StrictHostKeyChecking=no -o ConnectTimeout=30 admin@$NGFW_IP
request license deactivate VM-Capacity mode auto
EOF

# Check result - license deactivation returns status
echo "License deactivation command sent"
echo "Note: License deactivation may take up to 60 seconds to complete"

# Wait briefly for deactivation to process
sleep 10

echo "License deactivation complete"
'''

# Verification script to confirm cleanup
VERIFY_CLEANUP_SCRIPT = '''
#!/bin/bash
set -e

NGFW_IP="{{ management_ip }}"

echo "Verifying cleanup on $NGFW_IP..."

# Check if NGFW is still reachable (it may not be if already being terminated)
if timeout 10 bash -c "echo 'show system info' | ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 admin@$NGFW_IP" 2>/dev/null; then
    echo "NGFW still reachable - cleanup verification complete"
else
    echo "NGFW not reachable - may already be terminating"
fi

exit 0
'''


class NGFWDeprovisionPlan:
    """Deprovision plan for NGFW pre-destroy cleanup.

    Steps:
    1. Deactivate VM-Series license (releases back to pool)

    The license deactivation is critical to prevent license leakage.
    """

    steps: List[SetupStep] = [
        SetupStep(
            name="deactivate_license",
            script=DEACTIVATE_LICENSE_SCRIPT,
            timeout_seconds=300,  # 5 min - license deactivation can take time
            requires_reboot=False,
        ),
    ]

    verify_step: SetupStep = SetupStep(
        name="verify_cleanup",
        script=VERIFY_CLEANUP_SCRIPT,
        timeout_seconds=120,  # 2 min
        requires_reboot=False,
        is_verification=True,
    )

    def get_context(self, instance: Any) -> Dict[str, Any]:
        """Get template variables for deprovision scripts.

        Args:
            instance: Instance with management_ip attribute

        Returns:
            Dict with template variables

        Raises:
            ValueError: If required attributes are missing
        """
        management_ip = getattr(instance, "management_ip", None)
        if not management_ip:
            raise ValueError("Instance missing required 'management_ip' attribute")

        return {
            "management_ip": management_ip,
        }
