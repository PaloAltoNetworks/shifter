# POLARIS A2 — Install AD DS + DNS features and promote to a BOREAS.LOCAL
# forest. Runs via SSM Run Command after the stock Windows Server 2022 AMI
# is booted and SSM agent is online.
#
# This script schedules a one-shot scheduled task that runs
# a2_setup.ps1 after the post-promotion reboot, so the operator only has
# to trigger this one command to get from "blank Windows" to "BOREAS DC
# with users/groups/shares/flags".

[CmdletBinding()]
param(
    [string]$DsrmPassword       = "DsrmR3store!2026",
    [string]$AdminPassword      = "CortexSavesTheDay!",
    [string]$SetupScriptUri     = "https://shifter-polaris-bake-158151907940.s3.us-east-2.amazonaws.com/polaris/a2_setup.ps1",
    [string]$SetupScriptLocal   = "C:\polaris-a2-setup.ps1"
)

$ErrorActionPreference = "Stop"
$LogFile = "C:\polaris-install-adds.log"
Start-Transcript -Path $LogFile -Append -Force

Write-Host "=== POLARIS A2 install-adds $(Get-Date -Format o) ==="

# Defensive: firewall off (in case the first-boot user_data didn't persist
# this across reboots in a specific build).
Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled False

# Make sure Administrator password matches what the operator will use later.
net user Administrator $AdminPassword | Out-Null

# -----------------------------------------------------------------------
# Step 1: install AD DS + DNS features.
# -----------------------------------------------------------------------
$addsFeat = Get-WindowsFeature -Name AD-Domain-Services
if (-not $addsFeat.Installed) {
    Write-Host "  Installing AD-Domain-Services..."
    Install-WindowsFeature -Name AD-Domain-Services -IncludeManagementTools
}
$dnsFeat = Get-WindowsFeature -Name DNS
if (-not $dnsFeat.Installed) {
    Write-Host "  Installing DNS..."
    Install-WindowsFeature -Name DNS -IncludeManagementTools
}

# -----------------------------------------------------------------------
# Step 2: pre-download the post-promotion setup script and register a
# scheduled task that runs it once, at the SYSTEM user, after reboot +
# AD services are ready. Post-promotion SSM invocations are unreliable
# on Windows (the box renames, network stack churns, the agent may miss
# the first call window) — the scheduled-task pattern is the Packer /
# Terraform community standard for post-promotion config.
# -----------------------------------------------------------------------
Write-Host "  Downloading post-promotion setup script..."
Invoke-WebRequest -Uri $SetupScriptUri -OutFile $SetupScriptLocal -UseBasicParsing

# Schedule the setup to run once at next boot under SYSTEM. We use -AtStartup
# so it runs before any user logs on and doesn't require interactive auth.
$taskName = "PolarisA2Setup"
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}
$action  = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$SetupScriptLocal`" -AdminPassword `"$AdminPassword`""
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 1) -StartWhenAvailable
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings
Write-Host "  Scheduled task '$taskName' registered (will fire at next boot)"

# -----------------------------------------------------------------------
# Step 3: rename the computer to dc01 so AD uses that name after promotion.
# Rename-Computer normally wants a reboot, which Install-ADDSForest will
# give us, so we chain them.
# -----------------------------------------------------------------------
if ($env:COMPUTERNAME -ne "DC01") {
    Rename-Computer -NewName "dc01" -Force
    Write-Host "  Computer rename queued (dc01)"
}

# -----------------------------------------------------------------------
# Step 4: promote to a new forest. WinThreshold functional level supports
# everything the walkthrough attack chain needs.
# -----------------------------------------------------------------------
Import-Module ADDSDeployment
$secureDsrm = ConvertTo-SecureString $DsrmPassword -AsPlainText -Force

Write-Host "  Install-ADDSForest BOREAS.LOCAL (this reboots)..."
Install-ADDSForest `
    -DomainName "boreas.local" `
    -DomainNetbiosName "BOREAS" `
    -ForestMode "WinThreshold" `
    -DomainMode "WinThreshold" `
    -InstallDns `
    -DatabasePath "C:\Windows\NTDS" `
    -LogPath "C:\Windows\NTDS" `
    -SysvolPath "C:\Windows\SYSVOL" `
    -SafeModeAdministratorPassword $secureDsrm `
    -CreateDnsDelegation:$false `
    -NoRebootOnCompletion:$false `
    -Force:$true

# Unreachable unless Install-ADDSForest returned without rebooting.
Write-Host "=== Install-ADDSForest returned without reboot — check manually ==="
Stop-Transcript
