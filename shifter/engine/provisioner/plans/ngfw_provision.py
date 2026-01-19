"""NGFW Provision Plan for post-Pulumi NGFW configuration.

This plan runs after the NGFW EC2 instance is created to configure:
- Configure data interface (ethernet1/1) as Layer 3 DHCP with virtual router
- Create shared 'ranges' zone for all range traffic
- Delete default allow-all rule (bypasses per-range logging if left in place)
- Enable cloud logging (Strata Logging Service)
- Create log forwarding profile (XDR-Forward)

Note: No default security policy is created. Per-range security rules
are created by NGFWConfigureSubnetsPlan during range provisioning.

Commands are executed via SSHExecutor to the NGFW management interface.
All PAN-OS CLI commands have been validated against PAN-OS 11.x.

Note: SSH wait and serial number polling are handled by main.py.
Serial polling happens AFTER this plan completes, giving the device
time to complete license registration with the Palo Alto CSP.
"""

from typing import Any

from plans.base import SetupStep

# PAN-OS configure mode commands for data interface setup
# Configures ethernet1/1 as Layer 3 DHCP with virtual router for ENI routing
# Virtual router must be configured BEFORE the interface DHCP client
CONFIGURE_DATA_INTERFACE_INPUT = """configure
set network virtual-router default interface ethernet1/1
set network interface ethernet ethernet1/1 layer3 dhcp-client create-default-route no
commit
exit
"""

# PAN-OS configure mode commands for shared zone creation
# Creates 'ranges' zone used by all range traffic for XDR logging
CREATE_SHARED_ZONE_INPUT = """configure
set zone ranges network layer3 ethernet1/1
commit
exit
"""

# PAN-OS configure mode commands to delete default allow-all rule
# This rule bypasses per-range logging if left in place
DELETE_ALLOW_ALL_RULE_INPUT = """configure
delete rulebase security rules allow-all
commit
exit
"""

# PAN-OS configure mode commands for cloud logging (Step 12 from steps.md)
# Variables: {{ sls_region }}
ENABLE_CLOUD_LOGGING_INPUT = """configure
set deviceconfig setting logging logging-service-forwarding enable yes
set deviceconfig setting logging logging-service-forwarding logging-service-regions {{ sls_region }}
commit
exit
"""

# PAN-OS configure mode commands for log forwarding profile (Step 13 from steps.md)
CREATE_LOG_FORWARDING_PROFILE_INPUT = (
    "configure\n"
    "set shared log-settings profiles XDR-Forward match-list all-traffic log-type traffic "
    'filter "All Logs" send-to-panorama yes\n'
    "set shared log-settings profiles XDR-Forward enhanced-application-logging yes\n"
    "commit\n"
    "exit\n"
)

# Note: No default security policy is created here.
# Per-range security rules are created by NGFWConfigureSubnetsPlan
# during range provisioning, using the 'ranges' zone.


class NGFWProvisionPlan:
    """Provision plan for NGFW post-Pulumi configuration.

    Steps:
    1. Configure data interface (ethernet1/1 as L3 DHCP + virtual router)
    2. Create shared zone ('ranges') for all range traffic
    3. Delete default allow-all rule (bypasses per-range logging)
    4. Enable cloud logging (Strata Logging Service)
    5. Create log forwarding profile (XDR-Forward)

    Note: No default security policy is created. Per-range rules are created
    by NGFWConfigureSubnetsPlan during range provisioning.

    All commands are executed via SSHExecutor to the NGFW management interface.
    SSH wait is handled by main.py before this plan runs.
    Serial number polling happens after this plan completes (in main.py).
    """

    name = "ngfw_provision"

    def __init__(self) -> None:
        """Initialize plan with steps as instance attributes."""
        self.steps: list[SetupStep] = [
            # Configure data interface for direct ENI routing
            SetupStep(
                name="configure_data_interface",
                script="",  # Empty - commands sent via stdin
                stdin_input=CONFIGURE_DATA_INTERFACE_INPUT,
                timeout_seconds=300,  # 5 min - config + commit
            ),
            # Create shared zone for all range traffic
            SetupStep(
                name="create_shared_zone",
                script="",
                stdin_input=CREATE_SHARED_ZONE_INPUT,
                timeout_seconds=300,  # 5 min - config + commit
            ),
            # Delete default allow-all rule (bypasses per-range logging)
            SetupStep(
                name="delete_allow_all_rule",
                script="",
                stdin_input=DELETE_ALLOW_ALL_RULE_INPUT,
                timeout_seconds=300,  # 5 min - config + commit
            ),
            # Enable cloud logging
            SetupStep(
                name="enable_cloud_logging",
                script="",
                stdin_input=ENABLE_CLOUD_LOGGING_INPUT,
                timeout_seconds=300,  # 5 min - config + commit
            ),
            # Create log forwarding profile
            SetupStep(
                name="create_log_forwarding_profile",
                script="",
                stdin_input=CREATE_LOG_FORWARDING_PROFILE_INPUT,
                timeout_seconds=300,  # 5 min - config + commit
            ),
        ]
        # No verify_step - verification is handled by poll_for_serial_and_cert()
        # in main.py which polls for both serial AND device certificate
        self.verify_step: SetupStep | None = None

    def get_context(self, instance: Any) -> dict[str, Any]:
        """Get template variables for NGFW provision steps.

        Args:
            instance: Instance with management_ip and sls_region attributes

        Returns:
            Dict with template variables

        Raises:
            ValueError: If required attributes are missing
        """
        management_ip = getattr(instance, "management_ip", None)
        if not management_ip:
            raise ValueError("Instance missing required 'management_ip' attribute")

        sls_region = getattr(instance, "sls_region", "americas")

        return {
            "management_ip": management_ip,
            "sls_region": sls_region,
        }
