"""NGFW Provision Plan for post-Pulumi NGFW configuration.

This plan runs after the NGFW EC2 instance is created to configure:
- Configure data interface (ethernet1/1) as Layer 3 DHCP with virtual router
- Create shared 'ranges' zone for all range traffic
- Delete default allow-all rule (bypasses per-range logging if left in place)
- Enable cloud logging (Strata Logging Service)
- Create log forwarding profile (XDR-Forward)
- Create alert-only security profiles (virus, spyware, vulnerability, etc.)
- Create profile-group bundling all security profiles
- Download and install threat content (Apps + Threats package)

Note: No default security policy is created. Per-range security rules
are created by NGFWConfigureSubnetsPlan during range provisioning.
The ALERT_PROFILE_GROUP is attached to those rules for threat detection.

Commands are executed via SSHExecutor to the NGFW management interface.
All PAN-OS CLI commands have been validated against PAN-OS 11.x.

Note: SSH wait and serial number polling are handled by main.py.
Serial polling happens AFTER this plan completes, giving the device
time to complete license registration with the Palo Alto CSP.
"""

from typing import Any

from engine.provisioner.plans.base import SetupStep

# Profile group name used for security rules - must match what's created below
# and referenced in ngfw_configure_subnets.py when attaching to rules
ALERT_PROFILE_GROUP = "Alert-Group"

# Zone protection profile - DISABLED
# Zone protection profiles drop traffic when flood thresholds are exceeded,
# there's no "allow" action. Since this is a controlled cyber range, we don't
# need DoS protection and it interferes with attack traffic flow.

# PAN-OS configure mode commands for data interface setup
# Configures ethernet1/1 as Layer 3 DHCP with virtual router for ENI routing
# Interface must be configured as layer3 BEFORE adding to virtual-router
CONFIGURE_DATA_INTERFACE_INPUT = """configure
set network interface ethernet ethernet1/1 layer3 dhcp-client create-default-route no
set network virtual-router default interface ethernet1/1
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
# Includes all log types for comprehensive XDR visibility in the cyber range:
# - traffic: Network traffic logs
# - threat: Security profile alerts (AV, spyware, vulnerability, etc.)
# - url: URL filtering logs
# - wildfire: WildFire cloud analysis logs
# - data: Data filtering/DLP logs
# - tunnel: Tunnel inspection logs
# - auth: Authentication logs
CREATE_LOG_FORWARDING_PROFILE_INPUT = (
    "configure\n"
    "set shared log-settings profiles XDR-Forward match-list all-traffic log-type traffic "
    'filter "All Logs" send-to-panorama yes\n'
    "set shared log-settings profiles XDR-Forward match-list all-threats log-type threat "
    'filter "All Logs" send-to-panorama yes\n'
    "set shared log-settings profiles XDR-Forward match-list all-url log-type url "
    'filter "All Logs" send-to-panorama yes\n'
    "set shared log-settings profiles XDR-Forward match-list all-wildfire log-type wildfire "
    'filter "All Logs" send-to-panorama yes\n'
    "set shared log-settings profiles XDR-Forward match-list all-data log-type data "
    'filter "All Logs" send-to-panorama yes\n'
    "set shared log-settings profiles XDR-Forward match-list all-tunnel log-type tunnel "
    'filter "All Logs" send-to-panorama yes\n'
    "set shared log-settings profiles XDR-Forward match-list all-auth log-type auth "
    'filter "All Logs" send-to-panorama yes\n'
    "set shared log-settings profiles XDR-Forward enhanced-application-logging yes\n"
    "commit\n"
    "exit\n"
)

# PAN-OS configure mode commands for alert-only security profiles
# These profiles detect threats without blocking traffic (action=alert)
# All profiles are bundled into ALERT_PROFILE_GROUP for easy attachment to rules
#
# Profile types created:
#   - virus (Alert-Only-AV): Antivirus scanning for all protocols
#   - spyware (Alert-Only-AS): Anti-spyware/botnet detection
#   - vulnerability (Alert-Only-VP): Vulnerability/exploit detection
#   - url-filtering (Alert-Only-URL): URL category alerting
#   - file-blocking (Alert-Only-FB): File type alerting
#   - wildfire-analysis (Alert-Only-WF): Cloud sandbox analysis
#   - profile-group (Alert-Group): Bundle of all above profiles
#
# Note: Zone protection profiles are NOT created - they drop traffic when
# flood thresholds are exceeded with no "allow" action available.
CREATE_SECURITY_PROFILES_INPUT = f"""configure
set profiles virus Alert-Only-AV decoder http action alert
set profiles virus Alert-Only-AV decoder ftp action alert
set profiles virus Alert-Only-AV decoder smb action alert
set profiles virus Alert-Only-AV decoder smtp action alert
set profiles virus Alert-Only-AV decoder imap action alert
set profiles virus Alert-Only-AV decoder pop3 action alert
set profiles spyware Alert-Only-AS rules Alert-All action alert
set profiles spyware Alert-Only-AS rules Alert-All severity any
set profiles spyware Alert-Only-AS rules Alert-All threat-name any
set profiles spyware Alert-Only-AS rules Alert-All category any
set profiles vulnerability Alert-Only-VP rules Alert-All action alert
set profiles vulnerability Alert-Only-VP rules Alert-All severity any
set profiles vulnerability Alert-Only-VP rules Alert-All threat-name any
set profiles vulnerability Alert-Only-VP rules Alert-All category any
set profiles vulnerability Alert-Only-VP rules Alert-All cve any
set profiles vulnerability Alert-Only-VP rules Alert-All host any
set profiles vulnerability Alert-Only-VP rules Alert-All vendor-id any
set profiles url-filtering Alert-Only-URL category command-and-control action alert
set profiles url-filtering Alert-Only-URL category malware action alert
set profiles url-filtering Alert-Only-URL category phishing action alert
set profiles url-filtering Alert-Only-URL category grayware action alert
set profiles url-filtering Alert-Only-URL category ransomware action alert
set profiles file-blocking Alert-Only-FB rules Alert-All action alert
set profiles file-blocking Alert-Only-FB rules Alert-All application any
set profiles file-blocking Alert-Only-FB rules Alert-All file-type any
set profiles file-blocking Alert-Only-FB rules Alert-All direction both
set profiles wildfire-analysis Alert-Only-WF rules Forward-All application any
set profiles wildfire-analysis Alert-Only-WF rules Forward-All file-type any
set profiles wildfire-analysis Alert-Only-WF rules Forward-All direction both
set profiles wildfire-analysis Alert-Only-WF rules Forward-All analysis public-cloud
set profile-group {ALERT_PROFILE_GROUP} virus Alert-Only-AV
set profile-group {ALERT_PROFILE_GROUP} spyware Alert-Only-AS
set profile-group {ALERT_PROFILE_GROUP} vulnerability Alert-Only-VP
set profile-group {ALERT_PROFILE_GROUP} url-filtering Alert-Only-URL
set profile-group {ALERT_PROFILE_GROUP} file-blocking Alert-Only-FB
set profile-group {ALERT_PROFILE_GROUP} wildfire-analysis Alert-Only-WF
commit
exit
"""

# Note: No default security policy is created here.
# Per-range security rules are created by NGFWConfigureSubnetsPlan
# during range provisioning, using the 'ranges' zone.
# Those rules attach ALERT_PROFILE_GROUP for threat detection.

# PAN-OS operational commands for content download
# Downloads latest threat content (Apps + Threats package)
# Command is async - returns job ID, requires polling for completion
DOWNLOAD_CONTENT_INPUT = "request content upgrade download latest\n"

# PAN-OS operational commands for content install
# Installs the downloaded threat content
# Command is async - returns job ID, requires polling for completion
INSTALL_CONTENT_INPUT = "request content upgrade install version latest\n"


class NGFWProvisionPlan:
    """Provision plan for NGFW post-Pulumi configuration.

    Steps:
    1. Configure data interface (ethernet1/1 as L3 DHCP + virtual router)
    2. Create shared zone ('ranges') for all range traffic
    3. Delete default allow-all rule (bypasses per-range logging)
    4. Enable cloud logging (Strata Logging Service)
    5. Create log forwarding profile (XDR-Forward)
    6. Create alert-only security profiles and profile-group:
       - virus (Alert-Only-AV), spyware (Alert-Only-AS), vulnerability (Alert-Only-VP)
       - url-filtering (Alert-Only-URL), file-blocking (Alert-Only-FB)
       - wildfire-analysis (Alert-Only-WF)
       - profile-group (ALERT_PROFILE_GROUP) bundling all above
    7. Download threat content (Apps + Threats package)
    8. Install threat content

    Note: No default security policy is created. Per-range rules are created
    by NGFWConfigureSubnetsPlan during range provisioning. Those rules
    attach ALERT_PROFILE_GROUP for threat detection without blocking.

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
            # Create alert-only security profiles and profile-group
            # These profiles detect threats without blocking (action=alert)
            SetupStep(
                name="create_security_profiles",
                script="",
                stdin_input=CREATE_SECURITY_PROFILES_INPUT,
                timeout_seconds=300,  # 5 min - config + commit
            ),
            # Download threat content (async - polls for job completion)
            SetupStep(
                name="download_threat_content",
                script="",
                stdin_input=DOWNLOAD_CONTENT_INPUT,
                timeout_seconds=600,  # 10 min - download can take a while
                poll_for_job=True,
            ),
            # Install threat content (async - polls for job completion)
            SetupStep(
                name="install_threat_content",
                script="",
                stdin_input=INSTALL_CONTENT_INPUT,
                timeout_seconds=600,  # 10 min - install can take a while
                poll_for_job=True,
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
