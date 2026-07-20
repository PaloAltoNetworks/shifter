# AWS-only (issue #1633): add a first-boot EC2Launch v2 preReady task that resets
# the active DHCP adapter(s) to their DHCP-provided DNS so Windows range-guest DNS
# is deterministic before the default postReady startSsm task runs.
#
# Scope discipline:
#   - preReady stage: runs before startSsm, so the SSM agent registers against a
#     known-good resolver.
#   - frequency: once: runs only on the first boot after sysprep and never again.
#     An 'always' task would re-apply DHCP DNS on every reboot and undo the
#     DomainJoinPlan switch of a member's DNS to the Domain Controller.
#   - Runtime discovery only: the baked task discovers the active DHCP adapter at
#     boot; it bakes no interface index, alias, adapter GUID, VPC CIDR, or DC
#     address into the image.
#   - Not for the promoted DC: a promoted DC owns its own DNS (points at itself
#     and forwards to AmazonProvidedDNS), so this script is wired into
#     windows.pkr.hcl only, never dc.pkr.hcl / polaris-dc.pkr.hcl.
#
# AWS-only: referenced solely by the top-level AWS windows.pkr.hcl. It must never
# be added to the shared scripts/windows tree, which the GCP and polaris-dc
# builds consume.
$ErrorActionPreference = "Stop"

$cfgPath = "C:\ProgramData\Amazon\EC2Launch\config\agent-config.yml"
$marker  = "shifter-1633-dns"

if (-not (Test-Path -Path $cfgPath)) {
    throw "EC2Launch v2 agent-config not found at $cfgPath - unsupported Windows first-boot stack"
}

# Idempotent: skip if the task is already baked in.
$raw = Get-Content -Raw -Path $cfgPath
if ($raw -match [regex]::Escape($marker)) {
    Write-Host "Shifter DNS preReady task already present; nothing to do"
    exit 0
}

$lines = New-Object System.Collections.Generic.List[string]
foreach ($line in (Get-Content -Path $cfgPath)) { $lines.Add($line) }

# Locate the preReady stage, then its tasks: key (before the next stage).
$stageIdx = -1
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match "^\s*-\s*stage:\s*preReady\s*$") { $stageIdx = $i; break }
}
if ($stageIdx -lt 0) { throw "preReady stage not found in $cfgPath" }

$tasksIdx = -1
for ($i = $stageIdx + 1; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match "^\s*-\s*stage:") { break }
    if ($lines[$i] -match "^\s*tasks:\s*$") { $tasksIdx = $i; break }
}
if ($tasksIdx -lt 0) { throw "preReady tasks: block not found in $cfgPath" }

# Match the indentation of the existing task list items so the inserted block is
# well-formed regardless of the base image's exact formatting.
$ti = "      "
for ($i = $tasksIdx + 1; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match "^(\s*)-\s*task:") { $ti = $Matches[1]; break }
    if ($lines[$i].Trim().Length -gt 0) { break }
}

$block = @(
    "$ti- task: executeScript",
    "$ti  inputs:",
    "$ti    - frequency: once",
    "$ti      type: powershell",
    "$ti      runAs: localSystem",
    "$ti      content: |-",
    "$ti        # $marker: reset active DHCP adapters to DHCP-provided DNS so",
    "$ti        # first-boot DNS is deterministic before startSsm (issue #1633).",
    "$ti        `$ErrorActionPreference = 'Stop'",
    "$ti        Get-NetIPInterface -AddressFamily IPv4 |",
    "$ti          Where-Object { `$_.Dhcp -eq 'Enabled' -and `$_.ConnectionState -eq 'Connected' } |",
    "$ti          ForEach-Object { Set-DnsClientServerAddress -InterfaceIndex `$_.InterfaceIndex -ResetServerAddresses }",
    "$ti        Register-DnsClient"
)

$lines.InsertRange($tasksIdx + 1, [string[]]$block)

# Write UTF-8 without BOM and with LF endings so EC2Launch parses it cleanly.
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($cfgPath, (($lines -join "`n") + "`n"), $utf8NoBom)

# Fail closed on an invalid config: the build must not ship an unparseable
# first-boot config.
$ec2 = "C:\Program Files\Amazon\EC2Launch\EC2Launch.exe"
if (-not (Test-Path -Path $ec2)) { throw "EC2Launch.exe not found at $ec2" }
& $ec2 validate
if ($LASTEXITCODE -ne 0) { throw "EC2Launch.exe validate failed (exit $LASTEXITCODE)" }

Write-Host "Baked EC2Launch v2 preReady DNS task and validated agent-config.yml"
