# dc-prebaked bake-time promotion.
#
# Runs on the packer builder over WinRM. Installs AD DS + DNS, disables the
# firewall (the CTF DC serves LDAP/Kerberos/SMB/GC to the range), and promotes a
# fresh forest for the profile's domain with -NoRebootOnCompletion so packer
# controls the reboot (a `windows-restart` provisioner follows). After the reboot
# the builder comes back as the domain controller; the WinRM reconnect
# authenticates as the domain Administrator (same password as the built-in
# Administrator set in the DC WinRM bootstrap), and finalize.ps1 seeds the AD
# content.
#
# The domain and NetBIOS name come from the packer profile via the DC_DOMAIN_NAME
# / DC_NETBIOS_NAME environment variables (dc-profiles/<profile>.pkrvars.hcl ->
# dc-prebaked.pkr.hcl environment_vars). They default to boreas.local / BOREAS so
# a bare build reproduces the Polaris DC.
#
# Promotion is done at bake time (not first boot) so every range boots an
# already-promoted DC - fast spin-up, no per-range ~15-20 minute promotion. The
# image is captured un-sysprepped because GCESysprep cannot generalize a
# promoted domain controller (and on GDC there is no metadata server to answer
# a sysprepped image's OOBE, which is why the earlier sysprepped build hung with
# no network).
[CmdletBinding()]
param(
    [string]$DnsForwarder = "8.8.8.8"
)
$ErrorActionPreference = "Stop"
Start-Transcript -Path "C:\dc-prebaked-promote-bake.log" -Append -Force

# The DSRM (Directory Services Restore Mode) secret is baked into the forest, so
# it must NOT be a committed default: a shared, source-controlled DSRM password
# would ship in every promoted DC image. It is generated per build and injected
# as a sensitive Packer env var (DC_DSRM_PASSWORD); cleanup.ps1 strips the build
# transcript before capture. Refuse to promote without it.
$DsrmPassword = $env:DC_DSRM_PASSWORD
if ([string]::IsNullOrWhiteSpace($DsrmPassword)) {
    throw "DC_DSRM_PASSWORD is required (generated per build, injected as a sensitive Packer var); refusing to bake a DC with a default DSRM secret."
}

$DomainName = if ($env:DC_DOMAIN_NAME) { $env:DC_DOMAIN_NAME } else { "boreas.local" }
$NetbiosName = if ($env:DC_NETBIOS_NAME) { $env:DC_NETBIOS_NAME } else { "BOREAS" }
Write-Host "=== dc-prebaked promote-bake $(Get-Date -Format o) (domain $DomainName / $NetbiosName) ==="

# The DC serves AD to the whole range; the CTF design runs it firewall-off
# (a2_setup assumes reachable LDAP/SMB/etc.).
Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled False

foreach ($feat in @("AD-Domain-Services", "DNS")) {
    if (-not (Get-WindowsFeature -Name $feat).Installed) {
        Write-Host "  installing feature $feat"
        Install-WindowsFeature -Name $feat -IncludeManagementTools
    }
}

# Note: the Windows hostname is intentionally NOT renamed. Renaming leaves a
# pending-rename that Install-ADDSForest refuses to run over (it needs its own
# reboot first), and the hostname is cosmetic here: the range DNS container is
# authoritative for the DC's name -> the DC IP, so participants resolve it
# regardless of the DC's Windows computer name, and Kerberos/LDAP key off the
# domain, not the host name.
Import-Module ADDSDeployment
$secureDsrm = ConvertTo-SecureString $DsrmPassword -AsPlainText -Force
Write-Host "  Install-ADDSForest $DomainName (reboot deferred to packer)..."
Install-ADDSForest `
    -DomainName $DomainName `
    -DomainNetbiosName $NetbiosName `
    -ForestMode "WinThreshold" `
    -DomainMode "WinThreshold" `
    -InstallDns `
    -DatabasePath "C:\Windows\NTDS" `
    -LogPath "C:\Windows\NTDS" `
    -SysvolPath "C:\Windows\SYSVOL" `
    -SafeModeAdministratorPassword $secureDsrm `
    -CreateDnsDelegation:$false `
    -NoRebootOnCompletion:$true `
    -Force:$true

# Stash the forwarder for finalize.ps1 (runs post-reboot, once DNS is serving).
Set-Content -Path "C:\dc-prebaked-dns-forwarder.txt" -Value $DnsForwarder -Encoding ascii
Write-Host "=== promote-bake complete (packer will reboot next) ==="
Stop-Transcript
