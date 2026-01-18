"""NGFW Provision Plan for post-Pulumi NGFW configuration.

This plan runs after the NGFW EC2 instance is created to configure:
- Configure data interface (ethernet1/1) as Layer 3 DHCP for ENI routing
- Enable cloud logging (Strata Logging Service)
- Create log forwarding profile (XDR-Forward)
- Create security policy (allow-all rule with logging)

Commands are executed via SSHExecutor to the NGFW management interface.
All PAN-OS CLI commands have been validated against PAN-OS 11.x.

Note: SSH wait and serial number polling are handled by main.py.
Serial polling happens AFTER this plan completes, giving the device
time to complete license registration with the Palo Alto CSP.
"""

from typing import Any, ClassVar

from plans.base import SetupStep

# PAN-OS configure mode commands for data interface setup
# Configures ethernet1/1 as Layer 3 DHCP for direct ENI routing (no GWLB/GENEVE)
CONFIGURE_DATA_INTERFACE_INPUT = """configure
set network interface ethernet ethernet1/1 layer3 dhcp-client
set zone untrust network layer3 ethernet1/1
set network virtual-router default interface ethernet1/1
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

# PAN-OS configure mode commands for security policy (Step 14 from steps.md)
CREATE_SECURITY_POLICY_INPUT = (
    "configure\n"
    "set rulebase security rules allow-all from any to any source any destination any "
    "application any service any action allow log-end yes log-setting XDR-Forward\n"
    "commit\n"
    "exit\n"
)


class NGFWProvisionPlan:
    """Provision plan for NGFW post-Pulumi configuration.

    Steps:
    1. Configure data interface (ethernet1/1 as L3 DHCP for ENI routing)
    2. Enable cloud logging (Strata Logging Service)
    3. Create log forwarding profile (XDR-Forward)
    4. Create security policy (allow-all rule)

    All commands are executed via SSHExecutor to the NGFW management interface.
    SSH wait is handled by main.py before this plan runs.
    Serial number polling happens after this plan completes (in main.py).
    """

    name: ClassVar[str] = "ngfw_provision"

    steps: ClassVar[list[SetupStep]] = [
        # Configure data interface for direct ENI routing
        SetupStep(
            name="configure_data_interface",
            script="",  # Empty - commands sent via stdin
            stdin_input=CONFIGURE_DATA_INTERFACE_INPUT,
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
        # Create security policy
        SetupStep(
            name="create_security_policy",
            script="",
            stdin_input=CREATE_SECURITY_POLICY_INPUT,
            timeout_seconds=300,  # 5 min - config + commit
        ),
    ]

    # No verify_step - verification is handled by poll_for_serial_and_cert()
    # in main.py which polls for both serial AND device certificate
    verify_step: ClassVar[SetupStep | None] = None

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
