<powershell>
# Windows DC user_data - intentionally minimal
# DC is promoted from prebaked AMI. Ansible verifies AD and installs XDR.
# SSH server is pre-baked in AMI with password auth enabled.

$LogFile = "C:\Windows\Temp\dc-userdata.log"
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"$timestamp - DC instance started. Ansible will verify via SSH." | Out-File -FilePath $LogFile

# Set hostname from scenario template
"$timestamp - Setting hostname to ${hostname}..." | Out-File -FilePath $LogFile -Append
Rename-Computer -NewName "${hostname}" -Force
"$timestamp - Hostname set" | Out-File -FilePath $LogFile -Append

# Set local Administrator password for pre-domain-promote access. Per-instance
# random value (#762). After Ansible promotes this host to a Domain
# Controller, the local Administrator account becomes the domain
# Administrator and its password is replaced by ``DC_DOMAIN_PASSWORD``
# (deployment-scoped, sourced from Secrets Manager via the engine
# provisioner ECS task). The literal is never logged.
# Issue #762: the per-instance local Administrator password (used
# for pre-domain-promote RDP) is set by the engine provisioner via
# SSM Run Command after this instance reports SSMAvailable — not in
# user_data. After Ansible promotes the host to a Domain Controller,
# the local Administrator account becomes the domain Administrator
# and its password is replaced by ``DC_DOMAIN_PASSWORD``
# (deployment-scoped, sourced from Secrets Manager via the engine
# provisioner ECS task). See
# shifter/engine/provisioner/plans/set_local_password_plan.py.
"$timestamp - Local Administrator password will be set by the engine provisioner post-boot via SSM Run Command" | Out-File -FilePath $LogFile -Append
</powershell>
