# polaris-dc bake -- install-on-virtio path.
#
# Runs (via the autounattend FirstLogonCommand) on a Windows Server 2022 guest
# installed DIRECTLY on the virtio disk. viostor (boot) + NetKVM (NIC) are
# auto-loaded during Windows Setup from the answer ISO's $WinPEDriver$ folder
# (W10\amd64 build -- this virtio-win ships no 2k22 dir), so the boot disk is
# virtio and viostor is boot-critical by construction. Because the build VM and
# every range boot the disk on the SAME virtio hardware, there is no bus switch,
# hence no hardware-change OOBE re-run; and no sysprep, so AD DS stays intact.
#
# Promotes a BOREAS.LOCAL forest and seeds the polaris AD content via
# a2_setup.ps1 (staged beside this script on the answer cdrom). The promotion
# reboots, so the seed phase runs from a SYSTEM AtStartup scheduled task. Writes
# C:\polaris\BAKE_DONE and shuts down cleanly for the golden-disk export.
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path C:\polaris | Out-Null
Start-Transcript -Path "C:\polaris\bake.log" -Append -Force
Write-Host "=== polaris-dc bake $(Get-Date -Format o) ==="

# Firewall OFF and network-location prompt suppressed FIRST, before any step that
# could block, so the DC is reachable on the range network no matter how far the
# rest of the bake gets. (An unanswered "allow discovery" prompt classifies the
# NIC as Public and drops inbound; disabling the profiles moots it.)
try {
    Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled False -ErrorAction SilentlyContinue
    New-Item "HKLM:\SYSTEM\CurrentControlSet\Control\Network\NewNetworkWindowOff" -Force -ErrorAction SilentlyContinue | Out-Null
} catch { Write-Host "firewall/net-prompt: $_" }

# Enable Windows SAC/EMS on serial (COM1) for a network-free operator console
# over the KubeVirt serial channel. Takes effect next boot.
try {
    bcdedit /ems "{current}" on | Out-Null
    bcdedit /emssettings EMSPORT:1 EMSBAUDRATE:115200 | Out-Null
    Write-Host "SAC/EMS enabled on COM1"
} catch { Write-Host "bcdedit ems error: $_" }

# Resolve this script's own directory (the answer cdrom) and copy a2_setup.ps1 to
# local disk (the cdrom letter can change across the promotion reboot; C: is stable).
$src = Split-Path -Parent $MyInvocation.MyCommand.Path
# Copy a2_setup.ps1 to local disk in the promote phase (when $src is the answer
# cdrom). Guard the self-copy: in the seed phase this script runs from
# C:\polaris, so $src == C:\polaris and Copy-Item onto itself throws under
# ErrorActionPreference=Stop, which would halt the bake before a2_setup runs.
if ($src -ne "C:\polaris") {
    Copy-Item (Join-Path $src "a2_setup.ps1") "C:\polaris\a2_setup.ps1" -Force
}

$phase = "C:\polaris\phase.txt"
$stage = if (Test-Path $phase) { Get-Content $phase -Raw } else { "promote" }

if ($stage.Trim() -eq "promote") {
    Set-Content -Path $phase -Value "seed" -Encoding ascii

    # Install the FULL virtio-win driver set into the OS from the virtio driver
    # cdrom -- not just NetKVM -- so every virtio device the GDC VM presents
    # (net, serial, balloon, rng, scsi, ...) has a matching driver instead of
    # sitting unconfigured in Device Manager. viostor (boot) is already present
    # from Setup's $WinPEDriver$ load. W10\amd64 is the right build for WS2022
    # (build 20348); this virtio-win ships no 2k22 dir.
    $vd = $null
    foreach ($v in (Get-Volume | Where-Object { $_.DriveLetter })) {
        if (Test-Path ($v.DriveLetter + ":\NetKVM")) { $vd = ($v.DriveLetter + ":"); break }
    }
    if ($vd) {
        Get-ChildItem "$vd\" -Recurse -Filter *.inf |
            Where-Object { $_.FullName -match '\\w10\\amd64\\' } |
            ForEach-Object { Write-Host "installing driver $($_.Name)"; & pnputil.exe /add-driver $_.FullName /install 2>&1 | Out-Null }
    } else { Write-Host "virtio driver cdrom not found (drivers may already be present from Setup)" }

    # Install the GDC guest agent so each range boot applies that range's assigned
    # NIC IP (Windows has no cloud-init on GDC; the provisioner sets the IP and the
    # agent applies it). install.ps1 registers a SYSTEM startup task that persists
    # in the golden image and re-runs against each range's own agent disks.
    $agentCd = (Get-Volume -FileSystemLabel "guest agent" -ErrorAction SilentlyContinue).DriveLetter
    if ($agentCd) {
        Write-Host "Installing GDC guest agent from ${agentCd}:\install.ps1"
        try { & "${agentCd}:\install.ps1" } catch { Write-Host "guest-agent install.ps1 error: $_" }
    } else {
        Write-Host "WARNING: GDC guest-agent cdrom (label 'guest agent') not found; NIC IP will not be applied"
    }

    # OpenSSH server -- best-effort and NON-BLOCKING. The OpenSSH.Server FoD source
    # may be unreachable on the build network and Add-WindowsCapability would hang
    # the whole bake; run it as a background job so it never blocks the promotion.
    Start-Job -ScriptBlock {
        Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 -ErrorAction SilentlyContinue | Out-Null
        Set-Service -Name sshd -StartupType Automatic -ErrorAction SilentlyContinue
        Start-Service -Name sshd -ErrorAction SilentlyContinue
    } | Out-Null

    foreach ($feat in @("AD-Domain-Services", "DNS")) {
        if (-not (Get-WindowsFeature -Name $feat).Installed) {
            Install-WindowsFeature -Name $feat -IncludeManagementTools
        }
    }

    # Register the post-reboot seed phase as a SYSTEM AtStartup scheduled task.
    # RunOnce is unreliable on a fresh DC (the local-Administrator autologon it
    # depends on may not fire post-promotion); a SYSTEM AtStartup task runs
    # regardless. The seed phase unregisters it after writing BAKE_DONE.
    Copy-Item $MyInvocation.MyCommand.Path "C:\polaris\bake.ps1" -Force
    $act = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument '-NoProfile -ExecutionPolicy Bypass -File "C:\polaris\bake.ps1"'
    Register-ScheduledTask -TaskName "PolarisBakeSeed" -Action $act `
        -Trigger (New-ScheduledTaskTrigger -AtStartup) `
        -User "NT AUTHORITY\SYSTEM" -RunLevel Highest -Force | Out-Null

    Import-Module ADDSDeployment
    $dsrm = ConvertTo-SecureString "DsrmR3store!2026" -AsPlainText -Force
    Write-Host "Install-ADDSForest BOREAS.LOCAL (reboots)..."
    Install-ADDSForest `
        -DomainName "boreas.local" -DomainNetbiosName "BOREAS" `
        -ForestMode "WinThreshold" -DomainMode "WinThreshold" -InstallDns `
        -DatabasePath "C:\Windows\NTDS" -LogPath "C:\Windows\NTDS" -SysvolPath "C:\Windows\SYSVOL" `
        -SafeModeAdministratorPassword $dsrm -CreateDnsDelegation:$false `
        -NoRebootOnCompletion:$false -Force:$true
    Stop-Transcript
    return
}

# phase == seed: AD DS is up after the promotion reboot; seed the content.
Write-Host "=== polaris-dc bake seed phase $(Get-Date -Format o) ==="
Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled False -ErrorAction SilentlyContinue
$ok = $false
for ($i = 0; $i -lt 60; $i++) {
    try { Get-ADDomain -ErrorAction Stop | Out-Null; $ok = $true; break }
    catch { Write-Host "waiting for AD DS ($i)..."; Start-Sleep -Seconds 10 }
}
if (-not $ok) { throw "AD DS did not come up after promotion" }

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\polaris\a2_setup.ps1" -DnsForwarder "8.8.8.8"
if ($LASTEXITCODE -ne $null -and $LASTEXITCODE -ne 0) { throw "a2_setup failed: $LASTEXITCODE" }

Set-Content -Path "C:\polaris\BAKE_DONE" -Value (Get-Date -Format o) -Encoding ascii
# Unregister the seed task so it does not re-run when ranges boot the golden image.
Unregister-ScheduledTask -TaskName "PolarisBakeSeed" -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "=== polaris-dc bake complete; BAKE_DONE written; shutting down for golden export ==="
Stop-Transcript
Stop-Computer -Force
