# AWS polaris-dc bake finalize (runs after the promotion reboot, once packer has
# reconnected over WinRM as the domain Administrator). Waits for AD DS to serve,
# then runs the AD content seed (staged at C:\polaris\a2_setup.ps1 from
# var.dc_content_script, whose canonical Polaris input is
# scripts/windows/polaris-content-seed.ps1). It creates the
# OUs/users/groups/SPNs/DCSync ACL/flags/
# shares and sets the CTF Administrator password. MUST BE LAST provisioner before
# capture so the content seed's Administrator-password change breaks no later step.
#
# The Polaris content seed defaults its DNS forwarder to the link-local AWS
# Route 53 Resolver
# (169.254.169.253), so no forwarder is passed here. Unlike the GCE/GDC finalize
# there is no UEFI-fallback bootloader staging (AWS boots the AMI directly).
$ErrorActionPreference = "Stop"
Start-Transcript -Path "C:\polaris-dc-finalize.log" -Append -Force
Write-Host "=== polaris-dc finalize $(Get-Date -Format o) ==="

# Firewall stays off on the DC (assert again post-reboot).
Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled False

# Wait until AD DS answers before seeding.
$ok = $false
for ($i = 0; $i -lt 60; $i++) {
    try { Get-ADDomain -ErrorAction Stop | Out-Null; $ok = $true; break }
    catch { Write-Host "waiting for AD DS ($i)..."; Start-Sleep -Seconds 10 }
}
if (-not $ok) { throw "AD DS did not become available after promotion" }
Write-Host "AD DS is serving."

if (-not (Test-Path "C:\polaris\a2_setup.ps1")) {
    throw "C:\polaris\a2_setup.ps1 missing (file provisioner did not run)"
}
Write-Host "Running a2_setup.ps1..."
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\polaris\a2_setup.ps1"
if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) {
    throw "a2_setup.ps1 failed with exit code $LASTEXITCODE"
}
Write-Host "=== polaris-dc finalize complete ==="
Stop-Transcript
