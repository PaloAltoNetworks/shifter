<powershell>
# Windows victim instance setup script
# Minimal - Ansible handles setup via SSH (pre-baked in AMI)

$ErrorActionPreference = "Stop"
$LogFile = "C:\Windows\Temp\user-data.log"

function Log-Message {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$timestamp - $Message" | Out-File -FilePath $LogFile -Append
    Write-Host $Message
}

Log-Message "Victim Windows instance booting..."

# Set hostname from scenario template
Log-Message "Setting hostname to ${hostname}..."
Rename-Computer -NewName "${hostname}" -Force
Log-Message "Hostname set"

# Set Administrator password for RDP access
# TODO: Move to CMS-managed instance credentials (#542)
$AdminPassword = "CortexSavesTheDay!"
net user Administrator $AdminPassword
Log-Message "Administrator password configured"

# All setup (SSH keys, XDR) is handled by Ansible via SSH.
# SSH server is pre-baked in AMI with password auth enabled.

Log-Message "user_data complete. Ansible will handle remaining setup."
</powershell>
