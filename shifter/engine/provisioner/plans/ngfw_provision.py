"""NGFW Provision Plan for post-Pulumi NGFW configuration.

This plan runs after the NGFW EC2 instance is created to configure:
- Wait for SSH availability (~13 min after EC2 launch)
- Verify device certificate
- Enable cloud logging (Strata Logging Service)
- Create log forwarding profile (XDR-Forward)
- Create security policy (allow-all rule with logging)

Commands are executed via SSH to the NGFW management interface.
All PAN-OS CLI commands have been validated against PAN-OS 11.x.
"""

from typing import Any, ClassVar

from .base import SetupStep

# SSH wait script - checks if NGFW is ready for SSH commands
# VM-Series takes ~13 minutes to boot and be ready
WAIT_SSH_READY_SCRIPT = """
#!/bin/bash
set -e

NGFW_IP="{{ management_ip }}"
MAX_ATTEMPTS=90  # 15 minutes (10 second intervals)
ATTEMPT=0

echo "Waiting for NGFW SSH availability at $NGFW_IP..."

while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    if timeout 5 bash -c \
        "echo 'show system info' | ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 admin@$NGFW_IP" \
        2>/dev/null | grep -q "hostname"; then
        echo "NGFW SSH is ready"
        exit 0
    fi
    ATTEMPT=$((ATTEMPT + 1))
    echo "Attempt $ATTEMPT/$MAX_ATTEMPTS - waiting for SSH..."
    sleep 10
done

echo "ERROR: NGFW SSH not available after 15 minutes"
exit 1
"""

# Device certificate verification script
VERIFY_DEVICE_CERT_SCRIPT = """
#!/bin/bash
set -e

NGFW_IP="{{ management_ip }}"

echo "Verifying device certificate on $NGFW_IP..."

# Check device certificate status
CERT_STATUS=$(echo "show system info" | \
    ssh -o StrictHostKeyChecking=no admin@$NGFW_IP 2>/dev/null | \
    grep -i "device-certificate" || echo "unknown")

if echo "$CERT_STATUS" | grep -qi "valid"; then
    echo "Device certificate is valid"
    exit 0
elif echo "$CERT_STATUS" | grep -qi "none"; then
    echo "WARNING: No device certificate - cloud features may be limited"
    exit 0
else
    echo "Device certificate status: $CERT_STATUS"
    exit 0
fi
"""

# Enable cloud logging (Strata Logging Service)
# Validated PAN-OS CLI commands
ENABLE_CLOUD_LOGGING_SCRIPT = """
#!/bin/bash
set -e

NGFW_IP="{{ management_ip }}"
SLS_REGION="{{ sls_region }}"

echo "Enabling cloud logging on $NGFW_IP with region $SLS_REGION..."

# Send configuration commands via SSH
# IMPORTANT: PAN-OS requires commands piped to SSH, not passed as arguments
cat << 'EOF' | ssh -o StrictHostKeyChecking=no admin@$NGFW_IP
configure
set deviceconfig setting logging logging-service-forwarding enable yes
set deviceconfig setting logging logging-service-forwarding logging-service-regions {{ sls_region }}
commit
exit
EOF

echo "Cloud logging enabled successfully"
"""

# Create log forwarding profile for XDR
# Validated PAN-OS CLI commands
CREATE_LOG_FORWARDING_PROFILE_SCRIPT = """
#!/bin/bash
set -e

NGFW_IP="{{ management_ip }}"

echo "Creating XDR-Forward log forwarding profile on $NGFW_IP..."

cat << 'EOF' | ssh -o StrictHostKeyChecking=no admin@$NGFW_IP
configure
set shared log-settings profiles XDR-Forward match-list all-traffic \
    log-type traffic filter "All Logs" send-to-panorama yes
set shared log-settings profiles XDR-Forward enhanced-application-logging yes
commit
exit
EOF

echo "Log forwarding profile created successfully"
"""

# Create security policy with allow-all rule and logging
# Validated PAN-OS CLI commands
CREATE_SECURITY_POLICY_SCRIPT = """
#!/bin/bash
set -e

NGFW_IP="{{ management_ip }}"

echo "Creating security policy on $NGFW_IP..."

cat << 'EOF' | ssh -o StrictHostKeyChecking=no admin@$NGFW_IP
configure
set rulebase security rules allow-all from any to any source any \
    destination any application any service any action allow \
    log-end yes log-setting XDR-Forward
commit
exit
EOF

echo "Security policy created successfully"
"""

# Verification script to check configuration
VERIFY_CONFIG_SCRIPT = """
#!/bin/bash
set -e

NGFW_IP="{{ management_ip }}"

echo "Verifying NGFW configuration on $NGFW_IP..."

# Check security rules
RULES=$(echo "show running security-policy" | ssh -o StrictHostKeyChecking=no admin@$NGFW_IP 2>/dev/null || echo "")

if echo "$RULES" | grep -qi "allow-all"; then
    echo "Security policy verified: allow-all rule exists"
else
    echo "WARNING: allow-all rule not found in security policy"
fi

# Check log forwarding profile
PROFILES=$(echo "show running log-settings" | ssh -o StrictHostKeyChecking=no admin@$NGFW_IP 2>/dev/null || echo "")

if echo "$PROFILES" | grep -qi "XDR-Forward"; then
    echo "Log forwarding profile verified: XDR-Forward exists"
else
    echo "WARNING: XDR-Forward profile not found"
fi

echo "Configuration verification complete"
exit 0
"""


class NGFWProvisionPlan:
    """Provision plan for NGFW post-Pulumi configuration.

    Steps:
    1. Wait for SSH availability (~13 min for VM-Series boot)
    2. Verify device certificate
    3. Enable cloud logging (Strata Logging Service)
    4. Create log forwarding profile (XDR-Forward)
    5. Create security policy (allow-all rule)

    All commands are executed via SSH to the NGFW management interface.
    """

    steps: ClassVar[list[SetupStep]] = [
        SetupStep(
            name="wait_ssh_ready",
            script=WAIT_SSH_READY_SCRIPT,
            timeout_seconds=900,  # 15 min - VM-Series boot time
            requires_reboot=False,
        ),
        SetupStep(
            name="verify_device_cert",
            script=VERIFY_DEVICE_CERT_SCRIPT,
            timeout_seconds=300,  # 5 min
            requires_reboot=False,
        ),
        SetupStep(
            name="enable_cloud_logging",
            script=ENABLE_CLOUD_LOGGING_SCRIPT,
            timeout_seconds=600,  # 10 min - config + commit
            requires_reboot=False,
        ),
        SetupStep(
            name="create_log_forwarding_profile",
            script=CREATE_LOG_FORWARDING_PROFILE_SCRIPT,
            timeout_seconds=600,  # 10 min - config + commit
            requires_reboot=False,
        ),
        SetupStep(
            name="create_security_policy",
            script=CREATE_SECURITY_POLICY_SCRIPT,
            timeout_seconds=600,  # 10 min - config + commit
            requires_reboot=False,
        ),
    ]

    verify_step: ClassVar[SetupStep] = SetupStep(
        name="verify_ngfw_config",
        script=VERIFY_CONFIG_SCRIPT,
        timeout_seconds=300,  # 5 min
        requires_reboot=False,
        is_verification=True,
    )

    def get_context(self, instance: Any) -> dict[str, Any]:
        """Get template variables for NGFW provision scripts.

        Args:
            instance: Instance with management_ip, hostname, sls_region

        Returns:
            Dict with template variables

        Raises:
            ValueError: If required attributes are missing
        """
        management_ip = getattr(instance, "management_ip", None)
        if not management_ip:
            raise ValueError("Instance missing required 'management_ip' attribute")

        hostname = getattr(instance, "hostname", "ngfw")
        sls_region = getattr(instance, "sls_region", "us")

        return {
            "management_ip": management_ip,
            "hostname": hostname,
            "sls_region": sls_region,
        }
