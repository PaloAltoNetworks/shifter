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

$domain = "{{ domain_name }}"
$adminUser = "{{ domain_admin_user }}"
$adminPass = ConvertTo-SecureString "{{ domain_admin_password }}" -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential("$domain\\$adminUser", $adminPass)

# Wait for DC DNS to be ready (up to ~70s - prebaked DC should be fast)
Write-Host "Waiting for domain controller DNS to be ready..."
$maxAttempts = 7
$attempt = 0
$dnsReady = $false

while ($attempt -lt $maxAttempts -and -not $dnsReady) {
    $attempt++
    Write-Host "DNS check attempt $attempt of $maxAttempts..."

    try {
        # Try to resolve the domain
        $resolved = Resolve-DnsName -Name $domain -ErrorAction Stop
        if ($resolved) {
            Write-Host "Domain DNS resolved successfully"
            $dnsReady = $true
        }
    } catch {
        Write-Host "DNS not ready yet: $_"
        if ($attempt -lt $maxAttempts) {
            Write-Host "Waiting 10 seconds before retry..."
            Start-Sleep -Seconds 10
        }
    }
}

if (-not $dnsReady) {
    Write-Host "ERROR: Domain DNS not resolvable after $maxAttempts attempts"
    exit 1
}

# Now attempt domain join with retries
$joinAttempts = 3
$joinAttempt = 0
$joined = $false

while ($joinAttempt -lt $joinAttempts -and -not $joined) {
    $joinAttempt++
    Write-Host "Domain join attempt $joinAttempt of $joinAttempts..."

    try {
        Write-Host "Attempting to join domain: $domain"
        Add-Computer -DomainName $domain -Credential $cred -Force -ErrorAction Stop
        Write-Host "Domain join initiated successfully"
        Write-Host "Machine will restart to complete domain join"
        $joined = $true
    } catch {
        Write-Host "Join attempt failed: $_"
        if ($joinAttempt -lt $joinAttempts) {
            Write-Host "Waiting 15 seconds before retry..."
            Start-Sleep -Seconds 15
        }
    }
}

if ($joined) {
    exit 0
} else {
    Write-Host "ERROR: Domain join failed after $joinAttempts attempts"
    exit 1
}
'''

# PowerShell script to verify domain membership
# Includes retry logic to handle WMI not being ready immediately after reboot
VERIFY_DOMAIN_JOINED_SCRIPT = '''
$ErrorActionPreference = "Stop"

Write-Host "Verifying domain membership..."

$expectedDomain = "{{ domain_name }}"
$maxAttempts = 12
$retryDelaySeconds = 10
$attempt = 0
$verified = $false

while ($attempt -lt $maxAttempts -and -not $verified) {
    $attempt++
    Write-Host "Verification attempt $attempt of $maxAttempts..."

    try {
        # WMI may not be ready immediately after domain join reboot
        $computerSystem = Get-WmiObject Win32_ComputerSystem -ErrorAction Stop
        $currentDomain = $computerSystem.Domain

        Write-Host "Current domain: $currentDomain"
        Write-Host "Expected domain: $expectedDomain"

        if ($currentDomain -eq $expectedDomain) {
            Write-Host "Successfully joined domain: $currentDomain"
            $verified = $true
        } else {
            Write-Host "Domain mismatch - machine is in: $currentDomain"
            if ($attempt -lt $maxAttempts) {
                Write-Host "Domain membership may still be applying, retrying in $retryDelaySeconds seconds..."
                Start-Sleep -Seconds $retryDelaySeconds
            }
        }
    } catch {
        Write-Host "WMI query failed: $_"
        if ($attempt -lt $maxAttempts) {
            Write-Host "WMI service may still be initializing, retrying in $retryDelaySeconds seconds..."
            Start-Sleep -Seconds $retryDelaySeconds
        }
    }
}

if ($verified) {
    Write-Host "Domain join verification successful"
    exit 0
} else {
    Write-Host "ERROR: Domain join verification failed after $maxAttempts attempts"
    Write-Host "Expected domain: $expectedDomain"
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
            timeout_seconds=300,  # 5 min: DNS wait (1 min) + join retries (up to 1 min) + buffer
            requires_reboot=True,
        ),
    ]

    verify_step: SetupStep = SetupStep(
        name="verify_domain_joined",
        script=VERIFY_DOMAIN_JOINED_SCRIPT,
        timeout_seconds=180,  # 3 min: up to 12 retries with 10s delays
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
