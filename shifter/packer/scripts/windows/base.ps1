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
# Administrator Password
# ------------------------------------------------------------------------------
# NOTE: Password is set in sysprep.ps1 at the very end to avoid breaking
# the active WinRM session (which uses the AWS auto-generated password).
Write-Host "=== Administrator Password ==="
Write-Host "Skipping password change (will be set in sysprep.ps1)"

# ------------------------------------------------------------------------------
# Windows Firewall
# ------------------------------------------------------------------------------
Write-Host "=== Configuring Windows Firewall ==="

# Enable firewall on all profiles
Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled True

# Common rules for both victim and DC
New-NetFirewallRule -DisplayName "SSH Inbound" -Direction Inbound -Protocol TCP -LocalPort 22 -Action Allow -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName "WinRM HTTP Inbound" -Direction Inbound -Protocol TCP -LocalPort 5985 -Action Allow -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName "WinRM HTTPS Inbound" -Direction Inbound -Protocol TCP -LocalPort 5986 -Action Allow -ErrorAction SilentlyContinue

if ($Role -eq "victim") {
    # Victim-specific rules for web services
    New-NetFirewallRule -DisplayName "HTTP Inbound" -Direction Inbound -Protocol TCP -LocalPort 80 -Action Allow -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName "HTTPS Inbound" -Direction Inbound -Protocol TCP -LocalPort 443 -Action Allow -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName "MySQL Inbound" -Direction Inbound -Protocol TCP -LocalPort 3306 -Action Allow -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName "FTP Inbound" -Direction Inbound -Protocol TCP -LocalPort 21 -Action Allow -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName "FTP Passive Inbound" -Direction Inbound -Protocol TCP -LocalPort 1024-65535 -Action Allow -ErrorAction SilentlyContinue
    Write-Host "Victim firewall rules configured"
} else {
    # DC-specific rules for AD services
    New-NetFirewallRule -DisplayName "DNS TCP Inbound" -Direction Inbound -Protocol TCP -LocalPort 53 -Action Allow -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName "DNS UDP Inbound" -Direction Inbound -Protocol UDP -LocalPort 53 -Action Allow -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName "Kerberos TCP Inbound" -Direction Inbound -Protocol TCP -LocalPort 88 -Action Allow -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName "Kerberos UDP Inbound" -Direction Inbound -Protocol UDP -LocalPort 88 -Action Allow -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName "LDAP Inbound" -Direction Inbound -Protocol TCP -LocalPort 389 -Action Allow -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName "LDAPS Inbound" -Direction Inbound -Protocol TCP -LocalPort 636 -Action Allow -ErrorAction SilentlyContinue
    Write-Host "DC firewall rules configured"
}

Write-Host "Firewall rules configured"

# ------------------------------------------------------------------------------
# WinRM (Windows Remote Management)
# ------------------------------------------------------------------------------
# NOTE: WinRM is already configured by user_data in the Packer template.
# Don't reconfigure or restart it here - that kills the active Packer connection.
Write-Host "=== WinRM ==="
Write-Host "Skipping WinRM configuration (already configured by user_data)"

# ------------------------------------------------------------------------------
# Enable required Windows features
# ------------------------------------------------------------------------------
Write-Host "=== Enabling Windows features ==="

# Note: .NET Framework 4.8 is pre-installed on Windows Server 2022

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
