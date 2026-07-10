# dc-prebaked bake-time finalize (runs after the promotion reboot).
#
# The builder has rebooted as the profile's domain controller and packer has
# reconnected over WinRM as the domain Administrator. Wait for AD DS to serve,
# then run the AD content seed (staged at C:\polaris\a2_setup.ps1 from the
# profile's dc_content_script) which creates the OUs/users/groups/SPNs/DCSync
# ACL/flags/shares and sets the CTF Administrator password. This is the last
# provisioner before capture, so the content seed's Administrator-password change
# does not break any later WinRM step.
$ErrorActionPreference = "Stop"
Start-Transcript -Path "C:\dc-prebaked-finalize.log" -Append -Force
Write-Host "=== dc-prebaked finalize $(Get-Date -Format o) ==="

# Firewall stays off on the DC (assert again post-reboot).
Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled False

# Wait until AD Web Services / NTDS answer.
$ok = $false
for ($i = 0; $i -lt 60; $i++) {
    try { Get-ADDomain -ErrorAction Stop | Out-Null; $ok = $true; break }
    catch { Write-Host "waiting for AD DS ($i)..."; Start-Sleep -Seconds 10 }
}
if (-not $ok) { throw "AD DS did not become available after promotion" }
Write-Host "AD DS is serving."

$fwd = "8.8.8.8"
if (Test-Path "C:\dc-prebaked-dns-forwarder.txt") {
    $fwd = (Get-Content "C:\dc-prebaked-dns-forwarder.txt" -Raw).Trim()
}

if (-not (Test-Path "C:\polaris\a2_setup.ps1")) {
    throw "C:\polaris\a2_setup.ps1 missing (file provisioner did not run)"
}
Write-Host "Running a2_setup.ps1 (DNS forwarder $fwd)..."
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\polaris\a2_setup.ps1" -DnsForwarder $fwd
if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) {
    throw "a2_setup.ps1 failed with exit code $LASTEXITCODE"
}

# GDC's OVMF boots with empty NVRAM (the exported image loses its UEFI boot
# variables), so it does not know the "Windows Boot Manager" entry and falls
# back to the removable-media path \EFI\Boot\bootx64.efi. GCE Windows only ships
# \EFI\Microsoft\Boot\bootmgfw.efi, so OVMF loops on a boot entry that never
# chains into Windows. Copy the Windows Boot Manager to the fallback path so the
# firmware boots it. (bootmgfw.efi reads \EFI\Microsoft\Boot\BCD regardless of
# where it is launched from, so no BCD change is needed.)
Write-Host "Staging Windows bootloader at the UEFI fallback path..."
mountvol S: /S
try {
    if (-not (Test-Path "S:\EFI\Microsoft\Boot\bootmgfw.efi")) {
        throw "bootmgfw.efi not found on the ESP; cannot stage UEFI fallback"
    }
    New-Item -ItemType Directory -Path "S:\EFI\Boot" -Force | Out-Null
    Copy-Item "S:\EFI\Microsoft\Boot\bootmgfw.efi" "S:\EFI\Boot\bootx64.efi" -Force
    Write-Host "  copied bootmgfw.efi -> S:\EFI\Boot\bootx64.efi"
    Get-ChildItem "S:\EFI\Boot" | ForEach-Object { Write-Host "   ESP fallback: $($_.Name) $($_.Length)" }
}
finally {
    mountvol S: /D
}

Write-Host "=== polaris-dc finalize complete ==="
Stop-Transcript
