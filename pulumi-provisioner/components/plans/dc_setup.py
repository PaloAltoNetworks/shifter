"""DC (Domain Controller) setup plan.

Defines the steps to configure a Windows Server as an Active Directory
Domain Controller.
"""

from typing import Any, Dict, List

from ..setup_plan import SetupStep


# PowerShell script to install AD DS feature
INSTALL_AD_FEATURE_SCRIPT = '''
$ErrorActionPreference = "Stop"

Write-Host "Installing AD Domain Services feature..."

try {
    $result = Install-WindowsFeature -Name AD-Domain-Services -IncludeManagementTools -ErrorAction Stop

    if ($result.Success) {
        Write-Host "AD Domain Services feature installed successfully"
        if ($result.RestartNeeded -eq "Yes") {
            Write-Host "Restart required after feature installation"
        }
        exit 0
    } else {
        Write-Host "Feature installation failed"
        exit 1
    }
} catch {
    Write-Host "Error installing AD DS feature: $_"
    exit 1
}
'''

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

    Steps:
    1. Install AD DS feature (requires reboot)
    2. Promote to Domain Controller (requires reboot)

    Verification:
    - Check NTDS service is running
    - Query AD Domain Controller
    """

    steps: List[SetupStep] = [
        SetupStep(
            name="install_ad_feature",
            script=INSTALL_AD_FEATURE_SCRIPT,
            timeout_seconds=600,  # 10 minutes for feature install
            requires_reboot=True,
        ),
        SetupStep(
            name="promote_to_dc",
            script=PROMOTE_DC_SCRIPT,
            timeout_seconds=900,  # 15 minutes for DC promotion
            requires_reboot=True,  # DC restarts after promotion
        ),
    ]

    verify_step: SetupStep = SetupStep(
        name="verify_ad_running",
        script=VERIFY_AD_SCRIPT,
        timeout_seconds=120,
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

        # Optional attributes
        if hasattr(instance, "hostname") and instance.hostname:
            context["hostname"] = instance.hostname
        if hasattr(instance, "dc_hostname") and instance.dc_hostname:
            context["dc_hostname"] = instance.dc_hostname
        if hasattr(instance, "private_ip") and instance.private_ip:
            context["private_ip"] = instance.private_ip
        if hasattr(instance, "dc_ip") and instance.dc_ip:
            context["dc_ip"] = instance.dc_ip

        return context
