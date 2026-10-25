# dc-prebaked bake-time finalize (AWS; runs after the promotion reboot).
#
# The builder has rebooted as the profile's domain controller and packer has
# reconnected over WinRM as the domain Administrator. Wait for AD DS to serve,
# pin the DNS forwarder to the VPC-local AmazonProvidedDNS so external names
# (e.g. the regional SSM endpoint) resolve deterministically, run an optional
# content seed, then strip build artifacts before capture. This is the last
# provisioner before the un-sysprepped capture.
$ErrorActionPreference = "Stop"
Start-Transcript -Path "C:\dc-prebaked-finalize.log" -Append -Force
Write-Host "=== dc-prebaked finalize $(Get-Date -Format o) ==="

# Wait until AD DS answers.
$ok = $false
for ($i = 0; $i -lt 60; $i++) {
    try { Get-ADDomain -ErrorAction Stop | Out-Null; $ok = $true; break }
    catch { Write-Host "waiting for AD DS ($i)..."; Start-Sleep -Seconds 10 }
}
if (-not $ok) { throw "AD DS did not become available after promotion" }
Write-Host "AD DS is serving."

# promote-bake.ps1 disables every firewall profile before the promotion reboot.
# Verify the persisted fail-closed state rather than mutating profiles here.
$enabledFirewallProfiles = @(Get-NetFirewallProfile | Where-Object { $_.Enabled })
if ($enabledFirewallProfiles.Count -ne 0) {
    throw "Windows Firewall was re-enabled across the promotion reboot"
}
Write-Host "Windows Firewall remains disabled after promotion."

# Pin the promoted DC's DNS forwarder to the link-local AmazonProvidedDNS so the
# DC (which owns its own DNS and forwards outbound queries) resolves external
# names deterministically. This is the DC-role equivalent of the FallbackDNS
# baked into the Linux range guests (see docs/dev/aws-ami-seeding-runbook.md).
$fwd = "169.254.169.253"
if (Test-Path "C:\dc-prebaked-dns-forwarder.txt") {
    $fwd = (Get-Content "C:\dc-prebaked-dns-forwarder.txt" -Raw).Trim()
}
Write-Host "Setting DNS server forwarder to $fwd ..."
Get-DnsServerForwarder | ForEach-Object {
    foreach ($ip in $_.IPAddress) { Remove-DnsServerForwarder -IPAddress $ip.IPAddressToString -Force -ErrorAction SilentlyContinue }
}
Set-DnsServerForwarder -IPAddress $fwd -PassThru | Out-Null

# Optional content seed (advanced range domains). Base DCs have none; run it only
# when a build profile staged one.
if (Test-Path "C:\shifter-build\content-seed.ps1") {
    Write-Host "Running content-seed.ps1 (DNS forwarder $fwd)..."
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\shifter-build\content-seed.ps1" -DnsForwarder $fwd
    if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        throw "content-seed.ps1 failed with exit code $LASTEXITCODE"
    }
}

# Strip build artifacts (transcripts, DSRM/forwarder stashes, staged seed) so the
# captured AMI carries no build residue.
Write-Host "Cleaning up build artifacts..."
Stop-Transcript
foreach ($p in @(
    "C:\dc-prebaked-promote-bake.log",
    "C:\dc-prebaked-finalize.log",
    "C:\dc-prebaked-dns-forwarder.txt",
    "C:\shifter-build"
)) {
    Remove-Item -Path $p -Recurse -Force -ErrorAction SilentlyContinue
}
Write-Host "=== finalize complete ==="
