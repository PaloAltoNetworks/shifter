"""Domain join setup plan.

Defines the steps to join a Windows machine to an Active Directory domain.
This plan is executed by the DC after promotion, targeting each victim
that needs to be domain-joined.
"""

from typing import Any, Dict, List

from ..setup_plan import SetupStep


# PowerShell script to set DNS to point to DC
SET_DNS_SCRIPT = '''
$ErrorActionPreference = "Stop"

Write-Host "Setting DNS to Domain Controller..."

try {
    $dcIp = "{{ dc_ip }}"

    # Set DNS on all active network adapters
    $adapters = Get-NetAdapter | Where-Object { $_.Status -eq 'Up' }
    foreach ($adapter in $adapters) {
        Set-DnsClientServerAddress -InterfaceIndex $adapter.ifIndex -ServerAddresses $dcIp
        Write-Host "Set DNS to $dcIp on adapter: $($adapter.Name)"
    }

    Write-Host "DNS configuration completed"
    exit 0
} catch {
    Write-Host "Error setting DNS: $_"
    exit 1
}
'''

# PowerShell script to join the domain
JOIN_DOMAIN_SCRIPT = '''
$ErrorActionPreference = "Stop"

Write-Host "Joining domain..."

try {
    $domain = "{{ domain_name }}"
    $adminUser = "{{ domain_admin_user }}"
    $adminPass = ConvertTo-SecureString "{{ domain_admin_password }}" -AsPlainText -Force
    $cred = New-Object System.Management.Automation.PSCredential("$domain\\$adminUser", $adminPass)

    Write-Host "Attempting to join domain: $domain"
    Add-Computer -DomainName $domain -Credential $cred -Force -ErrorAction Stop

    Write-Host "Domain join initiated successfully"
    Write-Host "Machine will restart to complete domain join"
    exit 0
} catch {
    Write-Host "Error joining domain: $_"
    exit 1
}
'''

# PowerShell script to verify domain membership
VERIFY_DOMAIN_JOINED_SCRIPT = '''
$ErrorActionPreference = "Stop"

Write-Host "Verifying domain membership..."

try {
    $computerSystem = Get-WmiObject Win32_ComputerSystem
    $currentDomain = $computerSystem.Domain
    $expectedDomain = "{{ domain_name }}"

    Write-Host "Current domain: $currentDomain"
    Write-Host "Expected domain: $expectedDomain"

    if ($currentDomain -eq $expectedDomain) {
        Write-Host "Successfully joined domain: $currentDomain"
        exit 0
    } else {
        Write-Host "Domain join verification failed"
        Write-Host "Machine is in domain: $currentDomain"
        Write-Host "Expected to be in: $expectedDomain"
        exit 1
    }
} catch {
    Write-Host "Error verifying domain membership: $_"
    exit 1
}
'''


class DomainJoinPlan:
    """Setup plan for joining a Windows machine to AD domain.

    This plan is executed AFTER DC setup completes. It runs on each victim
    that needs to be domain-joined.

    Steps:
    1. Set DNS to point to DC (required for domain discovery)
    2. Join domain via Add-Computer (requires reboot)

    Verification:
    - Check that machine's domain matches expected domain
    """

    steps: List[SetupStep] = [
        SetupStep(
            name="set_dns",
            script=SET_DNS_SCRIPT,
            timeout_seconds=60,
        ),
        SetupStep(
            name="join_domain",
            script=JOIN_DOMAIN_SCRIPT,
            timeout_seconds=300,  # 5 min for domain join
            requires_reboot=True,
        ),
    ]

    verify_step: SetupStep = SetupStep(
        name="verify_domain_joined",
        script=VERIFY_DOMAIN_JOINED_SCRIPT,
        timeout_seconds=120,  # 2 min for verification
        is_verification=True,
    )

    def get_context(self, dc_config: Dict[str, Any]) -> Dict[str, Any]:
        """Get template variables for domain join scripts.

        Args:
            dc_config: Dict with dc_ip, domain_name, domain_admin_password,
                      and optionally domain_admin_user

        Returns:
            Dict with template variables

        Raises:
            ValueError: If required config is missing
        """
        required_keys = ["dc_ip", "domain_name", "domain_admin_password"]

        for key in required_keys:
            if key not in dc_config or dc_config[key] is None:
                raise ValueError(
                    f"dc_config missing required key '{key}' for domain join"
                )

        return {
            "dc_ip": dc_config["dc_ip"],
            "domain_name": dc_config["domain_name"],
            "domain_admin_user": dc_config.get("domain_admin_user", "Administrator"),
            "domain_admin_password": dc_config["domain_admin_password"],
        }
