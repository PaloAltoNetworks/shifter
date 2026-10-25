# dc-prebaked bake-time finalize (runs after the promotion reboot).
#
# The builder has rebooted as the profile's domain controller and packer has
# reconnected over WinRM as the domain Administrator. Wait for AD DS to serve,
# then run the explicitly supplied content seed. This is the last provisioner
# before capture because a seed may rotate the Administrator password. Remove
# the staged seed and transcripts inside this same authenticated session.
$ErrorActionPreference = "Stop"
Start-Transcript -Path "C:\dc-prebaked-finalize.log" -Append -Force
Write-Host "=== dc-prebaked finalize $(Get-Date -Format o) ==="

# Wait until AD Web Services / NTDS answer.
$ok = $false
for ($i = 0; $i -lt 60; $i++) {
    try { Get-ADDomain -ErrorAction Stop | Out-Null; $ok = $true; break }
    catch { Write-Host "waiting for AD DS ($i)..."; Start-Sleep -Seconds 10 }
}
if (-not $ok) { throw "AD DS did not become available after promotion" }
Write-Host "AD DS is serving."

# base.ps1 and promote-bake.ps1 disable every firewall profile before the
# promotion reboot. Do not mutate the profiles from this post-reboot WinRM
# command: the domain-profile transition can terminate the command with
# WinRM exit 16001. Verify the persisted fail-closed build state instead.
$enabledFirewallProfiles = @(Get-NetFirewallProfile | Where-Object { $_.Enabled })
if ($enabledFirewallProfiles.Count -ne 0) {
    throw "Windows Firewall was re-enabled across the promotion reboot"
}
Write-Host "Windows Firewall remains disabled after promotion."

$fwd = "8.8.8.8"
if (Test-Path "C:\dc-prebaked-dns-forwarder.txt") {
    $fwd = (Get-Content "C:\dc-prebaked-dns-forwarder.txt" -Raw).Trim()
}

if (-not (Test-Path "C:\shifter-build\content-seed.ps1")) {
    throw "C:\shifter-build\content-seed.ps1 missing (file provisioner did not run)"
}
Write-Host "Running content-seed.ps1 (DNS forwarder $fwd)..."
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\shifter-build\content-seed.ps1" -DnsForwarder $fwd
if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) {
    throw "content-seed.ps1 failed with exit code $LASTEXITCODE"
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

Write-Host "=== dc-prebaked finalize complete ==="

# --- Pre-capture cleanup (un-sysprepped image) --------------------------------
# The image is captured UN-SYSPREPPED (GCESysprep cannot generalize a promoted
# DC), so the usual sysprep-time credential/transcript disposal does not happen.
# Do it by hand HERE, in the still-authenticated finalize session: content-seed.ps1
# above reset the domain Administrator password, so a later separate provisioner
# could not reconnect over WinRM to run cleanup (#1343 codex review). Strip the
# staged AD-content seed (carries baked passwords), the DNS-forwarder handoff,
# and the promote-bake transcript. The EXAMPLE.TEST identity is intentional and
# left intact; the live Administrator credential is rotated per range at runtime
# by plans/dc_setup.py (DC_DOMAIN_PASSWORD).
Write-Host "Stripping build-time secret material before capture..."
Remove-Item -Path "C:\shifter-build\content-seed.ps1" -Force -ErrorAction SilentlyContinue
if ((Test-Path "C:\shifter-build") -and -not (Get-ChildItem "C:\shifter-build" -Force)) {
    Remove-Item -Path "C:\shifter-build" -Force -Recurse -ErrorAction SilentlyContinue
}
Remove-Item -Path "C:\dc-prebaked-dns-forwarder.txt" -Force -ErrorAction SilentlyContinue
Remove-Item -Path "C:\dc-prebaked-promote-bake.log" -Force -ErrorAction SilentlyContinue
# Fail-closed: the secret-bearing content seed must not survive into the image.
if (Test-Path "C:\shifter-build\content-seed.ps1") {
    throw "cleanup failed: content seed C:\shifter-build\content-seed.ps1 still present before capture"
}
Write-Host "=== pre-capture cleanup complete ==="
Stop-Transcript
# The finalize transcript is closed now; remove it last so no bake transcript
# survives into the captured image.
Remove-Item -Path "C:\dc-prebaked-finalize.log" -Force -ErrorAction SilentlyContinue
