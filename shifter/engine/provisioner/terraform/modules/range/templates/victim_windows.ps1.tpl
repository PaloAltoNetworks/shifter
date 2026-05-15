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

# Issue #762: the per-instance local Administrator password is set
# by the engine provisioner via SSM Run Command after this instance
# reports SSMAvailable — not in user_data. The password value never
# appears in EC2 user_data, IMDS, or process argv on this host. See
# shifter/engine/provisioner/plans/set_local_password_plan.py.

# All setup (SSH keys, XDR) is handled by Ansible via SSH.
# SSH server is pre-baked in AMI with password auth enabled.

Log-Message "user_data complete. Ansible will handle remaining setup."
</powershell>
