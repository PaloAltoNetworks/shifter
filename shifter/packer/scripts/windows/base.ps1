# Base system configuration for Windows AMI (victim or DC)
# SSM Agent, RDP, Windows Firewall, WinRM, and optionally AD DS feature
#
# Usage:
#   .\base.ps1           - Victim configuration (default)
#   .\base.ps1 -Role dc  - Domain Controller configuration
#   PACKER_ROLE=dc       - Environment variable (used by Packer)
param(
    [ValidateSet("victim", "dc")]
    [string]$Role = ""
)

# If no parameter provided, check environment variable (set by Packer)
if (-not $Role) {
    $Role = if ($env:PACKER_ROLE) { $env:PACKER_ROLE } else { "victim" }
}

$ErrorActionPreference = "Stop"

Write-Host "=== Starting base system configuration (Role: $Role) ==="

# ------------------------------------------------------------------------------
# SSM Agent
# ------------------------------------------------------------------------------
Write-Host "=== Configuring SSM Agent ==="

# SSM Agent is pre-installed on Windows Server 2022, just ensure it's running
$ssmService = Get-Service -Name "AmazonSSMAgent" -ErrorAction SilentlyContinue
if ($ssmService) {
    Set-Service -Name "AmazonSSMAgent" -StartupType Automatic
    Start-Service -Name "AmazonSSMAgent" -ErrorAction SilentlyContinue
    Write-Host "SSM Agent configured and started"
} else {
    Write-Host "SSM Agent not found - will be installed by EC2Launch on first boot"
}

# ------------------------------------------------------------------------------
# Enable Remote Desktop (RDP)
# ------------------------------------------------------------------------------
Write-Host "=== Enabling Remote Desktop ==="

# Enable RDP
Set-ItemProperty -Path "HKLM:\System\CurrentControlSet\Control\Terminal Server" -Name "fDenyTSConnections" -Value 0

# Enable Network Level Authentication (more secure)
Set-ItemProperty -Path "HKLM:\System\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp" -Name "UserAuthentication" -Value 1

# Ensure Remote Desktop Services is set to start automatically
Set-Service -Name "TermService" -StartupType Automatic
Start-Service -Name "TermService" -ErrorAction SilentlyContinue

Write-Host "Remote Desktop enabled"

# ------------------------------------------------------------------------------
# Set Administrator Password
# ------------------------------------------------------------------------------
Write-Host "=== Setting Administrator password ==="

$admin = [ADSI]"WinNT://./Administrator,user"
$admin.SetPassword("CortexSavesTheDay!")
$admin.SetInfo()

Write-Host "Administrator password set"

# ------------------------------------------------------------------------------
# Windows Firewall - Left at default (AWS Security Groups handle network access)
# ------------------------------------------------------------------------------
# NOTE: Don't modify firewall during Packer build - it can disrupt WinRM connection.
# AWS Security Groups provide network-level access control.
Write-Host "=== Windows Firewall ==="
Write-Host "Skipping firewall configuration (AWS Security Groups handle network access)"

# ------------------------------------------------------------------------------
# WinRM (Windows Remote Management)
# ------------------------------------------------------------------------------
Write-Host "=== Configuring WinRM ==="

# Enable WinRM service
Set-Service -Name "WinRM" -StartupType Automatic
Start-Service -Name "WinRM"

# Configure WinRM
winrm quickconfig -quiet
winrm set winrm/config/service '@{AllowUnencrypted="true"}'
winrm set winrm/config/service/auth '@{Basic="true"}'
winrm set winrm/config/winrs '@{MaxMemoryPerShellMB="1024"}'

# Set trusted hosts to allow connections from any host
Set-Item WSMan:\localhost\Client\TrustedHosts -Value "*" -Force

# Restart WinRM to apply changes
Restart-Service WinRM

Write-Host "WinRM configured and enabled"

# ------------------------------------------------------------------------------
# Enable required Windows features
# ------------------------------------------------------------------------------
Write-Host "=== Enabling Windows features ==="

# .NET Framework (required by many applications)
Enable-WindowsOptionalFeature -Online -FeatureName NetFx4-AdvSrvs -All -NoRestart -ErrorAction SilentlyContinue

if ($Role -eq "dc") {
    # Install AD DS feature (but do NOT promote - that happens at runtime)
    Write-Host "=== Installing AD DS Feature ==="
    Install-WindowsFeature -Name AD-Domain-Services -IncludeManagementTools

    $addsFeature = Get-WindowsFeature -Name AD-Domain-Services
    if ($addsFeature.Installed) {
        Write-Host "AD DS feature installed successfully"
    } else {
        Write-Error "AD DS feature installation failed"
        exit 1
    }

    # Also install DNS (required for DC)
    Install-WindowsFeature -Name DNS -IncludeManagementTools

    $dnsFeature = Get-WindowsFeature -Name DNS
    if ($dnsFeature.Installed) {
        Write-Host "DNS feature installed successfully"
    } else {
        Write-Error "DNS feature installation failed"
        exit 1
    }
}

Write-Host "=== Base system configuration complete ==="
