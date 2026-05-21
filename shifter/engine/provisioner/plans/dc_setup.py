"""DC (Domain Controller) setup plan.

Supports two operating modes:
- prebaked: DC image already has AD DS promoted
- runtime promotion: install/promote AD DS during setup
"""

from typing import Any, ClassVar

from .base import SetupStep

# PowerShell script to set Administrator credential
# Prebaked DC AMI may have unknown credential - reset to configured value
SET_ADMIN_CREDENTIAL_SCRIPT = """
$ErrorActionPreference = "Stop"

Write-Host "=========================================="
Write-Host "=== Setting Administrator Password ==="
Write-Host "=========================================="
Write-Host "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "Hostname: $env:COMPUTERNAME"

# Verify this is a Domain Controller
Write-Host ""
Write-Host "[Step 1] Verifying Domain Controller status..."
try {
    $dcInfo = Get-ADDomainController -ErrorAction Stop
    Write-Host "  SUCCESS: This is a Domain Controller"
    Write-Host "  Domain: $($dcInfo.Domain)"
    Write-Host "  HostName: $($dcInfo.HostName)"
    Write-Host "  Site: $($dcInfo.Site)"
} catch {
    Write-Host "  ERROR: Not a Domain Controller or AD services not running"
    Write-Host "  Exception: $($_.Exception.Message)"
    Write-Host "  Cannot set domain Administrator password on non-DC"
    exit 1
}

# Check current Administrator account status
Write-Host ""
Write-Host "[Step 2] Checking Administrator account status..."
try {
    $adminUser = Get-ADUser -Identity Administrator -Properties PasswordLastSet,Enabled,LockedOut -ErrorAction Stop
    Write-Host "  Account Enabled: $($adminUser.Enabled)"
    Write-Host "  Account LockedOut: $($adminUser.LockedOut)"
    Write-Host "  PasswordLastSet: $($adminUser.PasswordLastSet)"
} catch {
    Write-Host "  WARNING: Could not query Administrator account: $($_.Exception.Message)"
}

# Set the password
Write-Host ""
Write-Host "[Step 3] Setting Administrator password..."
$newPassword = ConvertTo-SecureString "{{ domain_admin_password }}" -AsPlainText -Force

try {
    Set-ADAccountPassword -Identity Administrator -Reset -NewPassword $newPassword -ErrorAction Stop
    Write-Host "  SUCCESS: Administrator password set via Set-ADAccountPassword"
} catch {
    Write-Host "  ERROR: Failed to set Administrator password"
    Write-Host "  Exception Type: $($_.Exception.GetType().FullName)"
    Write-Host "  Exception Message: $($_.Exception.Message)"
    if ($_.Exception.InnerException) {
        Write-Host "  Inner Exception: $($_.Exception.InnerException.Message)"
    }
    exit 1
}

# Verify RDP access is configured
Write-Host ""
Write-Host "[Step 4] Verifying RDP configuration..."
$rdpService = Get-Service -Name TermService -ErrorAction SilentlyContinue
Write-Host "  TermService Status: $($rdpService.Status)"

$rdpPort = Get-NetTCPConnection -LocalPort 3389 -State Listen -ErrorAction SilentlyContinue
if ($rdpPort) {
    Write-Host "  RDP Port 3389: LISTENING"
} else {
    Write-Host "  WARNING: RDP Port 3389 not listening"
}

Write-Host ""
Write-Host "=========================================="
Write-Host "=== Administrator Password Set ==="
Write-Host "=========================================="
"""

# PowerShell script to enable SSH with password auth
# Required for Guacamole SSH connections (AMI may have key-only auth)
# Windows OpenSSH has a Match Group administrators block that overrides global settings
ENABLE_SSH_AUTH_SCRIPT = """
$ErrorActionPreference = "Stop"

Write-Host "=== Enabling SSH Password Authentication ==="

$sshdConfigPath = "C:\\ProgramData\\ssh\\sshd_config"

if (-not (Test-Path $sshdConfigPath)) {
    Write-Host "ERROR: sshd_config not found at $sshdConfigPath"
    exit 1
}

# Read current config
$config = Get-Content $sshdConfigPath -Raw

# Enable password authentication at global level
$config = $config -replace '(?m)^#?PasswordAuthentication\\s+.*$', 'PasswordAuthentication yes'

# Ensure the global setting exists
if ($config -notmatch 'PasswordAuthentication yes') {
    $config += "`nPasswordAuthentication yes"
}

# Windows OpenSSH has Match Group administrators block that overrides global settings
# Add PasswordAuthentication yes inside that block
if ($config -match 'Match Group administrators') {
    Write-Host "Found Match Group administrators block, adding PasswordAuthentication yes"
    # Insert PasswordAuthentication yes after the Match Group administrators line
    $config = $config -replace '(Match Group administrators[^\\n]*\\n)', "`$1       PasswordAuthentication yes`n"
}

# Write updated config
Set-Content -Path $sshdConfigPath -Value $config -NoNewline
Write-Host "Updated sshd_config with PasswordAuthentication yes"

# Restart sshd to apply changes
Write-Host "Restarting sshd service..."
Restart-Service sshd -Force
Write-Host "sshd service restarted"

# Verify the change
$verifyConfig = Get-Content $sshdConfigPath | Select-String "PasswordAuthentication"
Write-Host "Verification: $verifyConfig"

Write-Host "=== SSH Password Authentication Enabled ==="
"""

# PowerShell script to promote server to Domain Controller
PROMOTE_DC_SCRIPT = """
$ErrorActionPreference = "Stop"

Write-Host "=========================================="
Write-Host "DC PROMOTION STARTING"
Write-Host "=========================================="
Write-Host "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "Hostname: $env:COMPUTERNAME"
Write-Host "Domain to create: {{ domain_name }}"
Write-Host "NetBIOS name: {{ netbios_name }}"
Write-Host ""

try {
    Write-Host "[Step 0] Detecting existing Domain Controller state..."
    try {
        Import-Module ActiveDirectory -ErrorAction Stop
        $existingDc = Get-ADDomainController -ErrorAction Stop
        Write-Host "  Domain Controller already configured: $($existingDc.HostName)"
        Write-Host "  Skipping runtime promotion"
        exit 0
    } catch {
        Write-Host "  No existing Domain Controller detected, continuing with promotion"
    }

    Write-Host "[Step 1] Converting passwords to SecureString..."
    $DsrmPassword = ConvertTo-SecureString "{{ dsrm_password }}" -AsPlainText -Force
    $DomainAdminPassword = ConvertTo-SecureString "{{ domain_admin_password }}" -AsPlainText -Force
    Write-Host "  Passwords converted successfully"

    Write-Host ""
    Write-Host "[Step 2] Checking AD DS feature is installed..."
    $addsFeature = Get-WindowsFeature -Name AD-Domain-Services
    Write-Host "  AD-Domain-Services installed: $($addsFeature.Installed)"
    Write-Host "  Install state: $($addsFeature.InstallState)"

    if (-not $addsFeature.Installed) {
        Write-Host "  Installing AD-Domain-Services feature..."
        Install-WindowsFeature -Name AD-Domain-Services -IncludeManagementTools -ErrorAction Stop | Out-Null
        Write-Host "  AD-Domain-Services feature installed"
    }

    Write-Host ""
    Write-Host "[Step 3] Installing AD DS Forest..."
    Write-Host "  DomainName: {{ domain_name }}"
    Write-Host "  DomainNetbiosName: {{ netbios_name }}"
    Write-Host "  InstallDns: Yes"
    Write-Host "  NoRebootOnCompletion: Yes"
    Write-Host ""
    Write-Host "  Starting Install-ADDSForest (this may take several minutes)..."

    $startTime = Get-Date
    Install-ADDSForest `
        -DomainName "{{ domain_name }}" `
        -DomainNetbiosName "{{ netbios_name }}" `
        -SafeModeAdministratorPassword $DsrmPassword `
        -InstallDns `
        -NoRebootOnCompletion `
        -Force `
        -ErrorAction Stop
    $endTime = Get-Date
    $duration = $endTime - $startTime

    Write-Host ""
    Write-Host "=========================================="
    Write-Host "DC PROMOTION COMPLETED SUCCESSFULLY"
    Write-Host "=========================================="
    Write-Host "Duration: $($duration.TotalSeconds) seconds"
    Write-Host "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Write-Host "Server will restart to complete domain controller configuration"
    Write-Host "=========================================="

    exit 0
} catch {
    Write-Host ""
    Write-Host "=========================================="
    Write-Host "DC PROMOTION FAILED"
    Write-Host "=========================================="
    Write-Host "Exception Type: $($_.Exception.GetType().FullName)"
    Write-Host "Exception Message: $($_.Exception.Message)"
    if ($_.Exception.InnerException) {
        Write-Host "Inner Exception: $($_.Exception.InnerException.Message)"
    }
    Write-Host "Stack Trace:"
    Write-Host $_.ScriptStackTrace
    Write-Host ""
    Write-Host "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Write-Host "=========================================="
    exit 1
}
"""

# PowerShell script to verify AD DS is running
# Includes retry logic - AD services may take time to fully start after reboot
VERIFY_AD_SCRIPT = """
$ErrorActionPreference = "Stop"

Write-Host "=========================================="
Write-Host "DC VERIFICATION STARTING"
Write-Host "=========================================="
Write-Host "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "Hostname: $env:COMPUTERNAME"

$maxAttempts = 15
$retryDelaySeconds = 20
$attempt = 0
$verified = $false

Write-Host "Will attempt verification up to $maxAttempts times with ${retryDelaySeconds}s delay between attempts"
Write-Host ""

while ($attempt -lt $maxAttempts -and -not $verified) {
    $attempt++
    Write-Host "=========================================="
    Write-Host "VERIFICATION ATTEMPT $attempt of $maxAttempts"
    Write-Host "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Write-Host "=========================================="

    $stepsPassed = 0
    $totalSteps = 4

    # Step 1: Check NTDS service
    Write-Host ""
    Write-Host "[Step 1/$totalSteps] Checking NTDS service..."
    try {
        $addsService = Get-Service -Name "NTDS" -ErrorAction Stop
        Write-Host "  NTDS service found"
        Write-Host "  Status: $($addsService.Status)"
        Write-Host "  StartType: $($addsService.StartType)"

        if ($addsService.Status -ne "Running") {
            Write-Host "  ERROR: NTDS service is not running (Status=$($addsService.Status))"
            Write-Host "  Waiting for service to start..."
        } else {
            Write-Host "  SUCCESS: NTDS service is running"
            $stepsPassed++
        }
    } catch {
        Write-Host "  ERROR: Failed to query NTDS service"
        Write-Host "  Exception Type: $($_.Exception.GetType().FullName)"
        Write-Host "  Exception Message: $($_.Exception.Message)"
    }

    # Step 2: Check AD DS module and domain controller
    Write-Host ""
    Write-Host "[Step 2/$totalSteps] Querying AD Domain Controller..."
    try {
        # First check if AD module is available
        $adModule = Get-Module -ListAvailable -Name ActiveDirectory
        if ($adModule) {
            Write-Host "  ActiveDirectory module version: $($adModule.Version)"
        } else {
            Write-Host "  WARNING: ActiveDirectory module not found in available modules"
        }

        Import-Module ActiveDirectory -ErrorAction Stop
        Write-Host "  ActiveDirectory module imported"

        $dc = Get-ADDomainController -ErrorAction Stop
        Write-Host "  SUCCESS: Domain Controller query succeeded"
        Write-Host "  HostName: $($dc.HostName)"
        Write-Host "  Domain: $($dc.Domain)"
        Write-Host "  Forest: $($dc.Forest)"
        Write-Host "  Site: $($dc.Site)"
        Write-Host "  IPv4Address: $($dc.IPv4Address)"
        Write-Host "  OperatingSystem: $($dc.OperatingSystem)"
        Write-Host "  IsGlobalCatalog: $($dc.IsGlobalCatalog)"
        Write-Host "  IsReadOnly: $($dc.IsReadOnly)"
        $stepsPassed++
    } catch {
        Write-Host "  ERROR: Failed to query AD Domain Controller"
        Write-Host "  Exception Type: $($_.Exception.GetType().FullName)"
        Write-Host "  Exception Message: $($_.Exception.Message)"
        if ($_.Exception.InnerException) {
            Write-Host "  Inner Exception: $($_.Exception.InnerException.Message)"
        }
    }

    # Step 3: Check AD Domain
    Write-Host ""
    Write-Host "[Step 3/$totalSteps] Querying AD Domain..."
    try {
        $domain = Get-ADDomain -ErrorAction Stop
        Write-Host "  SUCCESS: AD Domain query succeeded"
        Write-Host "  Name: $($domain.Name)"
        Write-Host "  DNSRoot: $($domain.DNSRoot)"
        Write-Host "  NetBIOSName: $($domain.NetBIOSName)"
        Write-Host "  DomainMode: $($domain.DomainMode)"
        Write-Host "  DistinguishedName: $($domain.DistinguishedName)"
        Write-Host "  PDCEmulator: $($domain.PDCEmulator)"
        Write-Host "  InfrastructureMaster: $($domain.InfrastructureMaster)"
        $stepsPassed++
    } catch {
        Write-Host "  ERROR: Failed to query AD Domain"
        Write-Host "  Exception Type: $($_.Exception.GetType().FullName)"
        Write-Host "  Exception Message: $($_.Exception.Message)"
        if ($_.Exception.InnerException) {
            Write-Host "  Inner Exception: $($_.Exception.InnerException.Message)"
        }
    }

    # Step 4: Check DNS service
    Write-Host ""
    Write-Host "[Step 4/$totalSteps] Checking DNS service..."
    try {
        $dnsService = Get-Service -Name "DNS" -ErrorAction Stop
        Write-Host "  DNS service found"
        Write-Host "  Status: $($dnsService.Status)"

        if ($dnsService.Status -eq "Running") {
            Write-Host "  SUCCESS: DNS service is running"
            $stepsPassed++
        } else {
            Write-Host "  WARNING: DNS service status is $($dnsService.Status)"
        }
    } catch {
        Write-Host "  ERROR: Failed to query DNS service"
        Write-Host "  Exception Type: $($_.Exception.GetType().FullName)"
        Write-Host "  Exception Message: $($_.Exception.Message)"
    }

    # Evaluate overall status
    Write-Host ""
    Write-Host "----------------------------------------"
    Write-Host "Attempt $attempt summary: $stepsPassed/$totalSteps steps passed"

    if ($stepsPassed -eq $totalSteps) {
        Write-Host "ALL STEPS PASSED - DC verification successful!"
        $verified = $true
    } else {
        Write-Host "INCOMPLETE: $($totalSteps - $stepsPassed) steps failed"
        if ($attempt -lt $maxAttempts) {
            Write-Host "Waiting $retryDelaySeconds seconds before retry..."
            Write-Host "----------------------------------------"
            Start-Sleep -Seconds $retryDelaySeconds
        }
    }
}

Write-Host ""
Write-Host "=========================================="
if ($verified) {
    Write-Host "DC VERIFICATION COMPLETED SUCCESSFULLY"
    Write-Host "Total attempts: $attempt"
    Write-Host "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Write-Host "=========================================="
    exit 0
} else {
    Write-Host "DC VERIFICATION FAILED"
    Write-Host "Exhausted all $maxAttempts attempts"
    Write-Host "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Write-Host "=========================================="

    # Final diagnostic dump
    Write-Host ""
    Write-Host "FINAL DIAGNOSTICS:"
    Write-Host "----------------------------------------"

    Write-Host "Services status:"
    Get-Service -Name NTDS,DNS,Netlogon,ADWS -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Host "  $($_.Name): $($_.Status)"
    }

    Write-Host ""
    Write-Host "Event log errors (last 10 from System):"
    Get-EventLog -LogName System -EntryType Error -Newest 10 -ErrorAction SilentlyContinue | ForEach-Object {
        $msg = $_.Message.Substring(0, [Math]::Min(200, $_.Message.Length))
        Write-Host "  [$($_.TimeGenerated)] $($_.Source): $msg..."
    }

    exit 1
}
"""


class DCSetupPlan:
    """Setup plan for Windows Domain Controller.

    In prebaked mode, this plan configures runtime settings and verifies AD.
    In runtime-promotion mode, it promotes the instance first, then applies the
    same runtime settings and verification.
    """

    verify_step: ClassVar[SetupStep] = SetupStep(
        name="verify_ad_running",
        script=VERIFY_AD_SCRIPT,
        timeout_seconds=900,  # 15 min - allows 15 retries x 20s delays + verification time
        is_verification=True,
    )

    def __init__(self, runtime_promotion: bool = False):
        self.runtime_promotion = runtime_promotion

    @property
    def steps(self) -> list[SetupStep]:
        steps: list[SetupStep] = []
        if self.runtime_promotion:
            steps.append(
                SetupStep(
                    name="promote_domain_controller",
                    script=PROMOTE_DC_SCRIPT,
                    timeout_seconds=1800,
                    requires_reboot=True,
                )
            )

        steps.extend(
            [
                SetupStep(
                    name="set_admin_password",
                    script=SET_ADMIN_CREDENTIAL_SCRIPT,
                    timeout_seconds=60,
                ),
                SetupStep(
                    name="enable_ssh_password_auth",
                    script=ENABLE_SSH_AUTH_SCRIPT,
                    timeout_seconds=60,
                ),
            ]
        )
        return steps

    def get_context(self, instance: Any) -> dict[str, Any]:
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
                raise ValueError(f"Instance missing required attribute '{attr}' for DC setup")
            context[attr] = value

        return context
