# Base system configuration for Windows victim AMI
# SSM Agent, Windows Firewall, and WinRM setup
$ErrorActionPreference = "Stop"

Write-Host "=== Starting base system configuration ==="

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
# Windows Firewall
# ------------------------------------------------------------------------------
Write-Host "=== Configuring Windows Firewall ==="

# Enable firewall on all profiles
Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled True

# Allow common inbound rules for victim services
# HTTP
New-NetFirewallRule -DisplayName "HTTP Inbound" -Direction Inbound -Protocol TCP -LocalPort 80 -Action Allow -ErrorAction SilentlyContinue
# HTTPS
New-NetFirewallRule -DisplayName "HTTPS Inbound" -Direction Inbound -Protocol TCP -LocalPort 443 -Action Allow -ErrorAction SilentlyContinue
# MySQL
New-NetFirewallRule -DisplayName "MySQL Inbound" -Direction Inbound -Protocol TCP -LocalPort 3306 -Action Allow -ErrorAction SilentlyContinue
# FTP
New-NetFirewallRule -DisplayName "FTP Inbound" -Direction Inbound -Protocol TCP -LocalPort 21 -Action Allow -ErrorAction SilentlyContinue
# FTP Passive
New-NetFirewallRule -DisplayName "FTP Passive Inbound" -Direction Inbound -Protocol TCP -LocalPort 1024-65535 -Action Allow -ErrorAction SilentlyContinue
# SSH
New-NetFirewallRule -DisplayName "SSH Inbound" -Direction Inbound -Protocol TCP -LocalPort 22 -Action Allow -ErrorAction SilentlyContinue
# WinRM HTTP
New-NetFirewallRule -DisplayName "WinRM HTTP Inbound" -Direction Inbound -Protocol TCP -LocalPort 5985 -Action Allow -ErrorAction SilentlyContinue
# WinRM HTTPS
New-NetFirewallRule -DisplayName "WinRM HTTPS Inbound" -Direction Inbound -Protocol TCP -LocalPort 5986 -Action Allow -ErrorAction SilentlyContinue

Write-Host "Firewall rules configured"

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

Write-Host "=== Base system configuration complete ==="
