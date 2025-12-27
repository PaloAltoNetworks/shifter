"""DC (Domain Controller) setup plan.

Defines the steps to promote a Windows Server (with AD DS feature prebaked)
to an Active Directory Domain Controller.
"""

from typing import Any, Dict, List

from ..setup_plan import SetupStep


# PowerShell script to promote server to Domain Controller
PROMOTE_DC_SCRIPT = '''
$ErrorActionPreference = "Stop"

Write-Host "Promoting server to Domain Controller..."

try {
    # Convert passwords to SecureString
    $DsrmPassword = ConvertTo-SecureString "{{ dsrm_password }}" -AsPlainText -Force
    $DomainAdminPassword = ConvertTo-SecureString "{{ domain_admin_password }}" -AsPlainText -Force

    # Install AD DS Forest
    Install-ADDSForest `
        -DomainName "{{ domain_name }}" `
        -DomainNetbiosName "{{ netbios_name }}" `
        -SafeModeAdministratorPassword $DsrmPassword `
        -InstallDns `
        -NoRebootOnCompletion `
        -Force `
        -ErrorAction Stop

    Write-Host "AD DS Forest installed successfully"
    Write-Host "Server will restart automatically to complete promotion"

    exit 0
} catch {
    Write-Host "Error promoting to Domain Controller: $_"
    exit 1
}
'''

# PowerShell script to verify AD DS is running
VERIFY_AD_SCRIPT = '''
$ErrorActionPreference = "Stop"

Write-Host "Verifying AD Domain Services..."

try {
    # Check if AD DS service is running
    $addsService = Get-Service -Name "NTDS" -ErrorAction Stop
    if ($addsService.Status -ne "Running") {
        Write-Host "NTDS service is not running"
        exit 1
    }
    Write-Host "NTDS service is running"

    # Check if we can query the domain controller
    $dc = Get-ADDomainController -ErrorAction Stop
    Write-Host "Domain Controller: $($dc.HostName)"
    Write-Host "Domain: $($dc.Domain)"
    Write-Host "Forest: $($dc.Forest)"
    Write-Host "Site: $($dc.Site)"

    # Check DNS is working
    $domain = Get-ADDomain -ErrorAction Stop
    Write-Host "Domain DN: $($domain.DistinguishedName)"

    Write-Host "AD DS verification completed successfully"
    exit 0
} catch {
    Write-Host "AD DS verification failed: $_"
    exit 1
}
'''


class DCSetupPlan:
    """Setup plan for Windows Domain Controller.

    This plan runs AFTER BootstrapPlan completes (hostname set, SSH configured,
    instance rebooted). The AMI has AD DS feature prebaked, so we only need
    to promote to DC.

    Steps:
    1. Promote to Domain Controller (requires reboot)

    Verification:
    - Check NTDS service is running
    - Query AD Domain Controller
    """

    steps: List[SetupStep] = [
        SetupStep(
            name="promote_to_dc",
            script=PROMOTE_DC_SCRIPT,
            timeout_seconds=900,  # 15 min - generous, will tune after data
            requires_reboot=True,
        ),
    ]

    verify_step: SetupStep = SetupStep(
        name="verify_ad_running",
        script=VERIFY_AD_SCRIPT,
        timeout_seconds=600,  # 10 min - generous for post-reboot SSM latency
        is_verification=True,
    )

    def get_context(self, instance: Any) -> Dict[str, Any]:
        """Get template variables for DC setup scripts.

        Args:
            instance: DC instance with domain configuration

        Returns:
            Dict with domain_name, netbios_name, dsrm_password, domain_admin_password

        Raises:
            ValueError: If required attributes are missing or None
        """
        required_attrs = [
            "domain_name",
            "netbios_name",
            "dsrm_password",
            "domain_admin_password",
        ]

        context = {}
        for attr in required_attrs:
            value = getattr(instance, attr, None)
            if value is None:
                raise ValueError(
                    f"Instance missing required attribute '{attr}' for DC setup"
                )
            context[attr] = value

        return context
