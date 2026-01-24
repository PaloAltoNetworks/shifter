<powershell>
# Windows DC user_data - intentionally minimal
# DC is promoted from prebaked AMI. Ansible verifies AD and installs XDR.
# SSH server is pre-baked in AMI with password auth enabled.

$LogFile = "C:\Windows\Temp\dc-userdata.log"
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"$timestamp - DC instance started. Ansible will verify via SSH." | Out-File -FilePath $LogFile

# Set Administrator password for RDP/SSH access
# TODO: Move to CMS-managed instance credentials (#542)
$AdminPassword = "CortexSavesTheDay!"
net user Administrator $AdminPassword
"$timestamp - Administrator password configured" | Out-File -FilePath $LogFile -Append
</powershell>
