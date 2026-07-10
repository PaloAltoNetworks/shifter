# Sysprep preparation for Windows GCE images.
#
# Mirrors the cleanup / service-hardening of the AWS sysprep
# (../../scripts/windows/sysprep.ps1) but finishes with GCESysprep — GCE images
# are generalized by the Google Compute Engine sysprep tool, not the AWS launch
# agent used on the AWS path.
$ErrorActionPreference = "Stop"

Write-Host "=== Preparing for GCE sysprep ==="

# ------------------------------------------------------------------------------
# Disable services that slow boot or conflict with XDR
# ------------------------------------------------------------------------------
Write-Host "=== Disabling unnecessary services ==="

$servicesToDisable = @(
    "Spooler",           # Print Spooler
    "RemoteRegistry",    # Remote Registry
    "edgeupdate",        # Microsoft Edge Update Service
    "edgeupdatem",       # Microsoft Edge Update Service (Manual Start)
    "Themes"             # Themes service
)

foreach ($service in $servicesToDisable) {
    $svc = Get-Service -Name $service -ErrorAction SilentlyContinue
    if ($svc) {
        Stop-Service -Name $service -Force -ErrorAction SilentlyContinue
        Set-Service -Name $service -StartupType Disabled -ErrorAction SilentlyContinue
        Write-Host "Disabled service: $service"
    } else {
        Write-Host "Service not found (skipping): $service"
    }
}

# ------------------------------------------------------------------------------
# Disable Windows Defender via Group Policy registry keys
# This is required for XDR agent to function properly
# ------------------------------------------------------------------------------
Write-Host "=== Disabling Windows Defender via registry ==="

$defenderPath = "HKLM:\SOFTWARE\Policies\Microsoft\Windows Defender"

if (-not (Test-Path $defenderPath)) {
    New-Item -Path $defenderPath -Force | Out-Null
}

Set-ItemProperty -Path $defenderPath -Name "DisableAntiSpyware" -Value 1 -Type DWord -Force
Set-ItemProperty -Path $defenderPath -Name "DisableAntiVirus" -Value 1 -Type DWord -Force

$rtpPath = "$defenderPath\Real-Time Protection"
if (-not (Test-Path $rtpPath)) {
    New-Item -Path $rtpPath -Force | Out-Null
}
Set-ItemProperty -Path $rtpPath -Name "DisableRealtimeMonitoring" -Value 1 -Type DWord -Force
Set-ItemProperty -Path $rtpPath -Name "DisableBehaviorMonitoring" -Value 1 -Type DWord -Force
Set-ItemProperty -Path $rtpPath -Name "DisableOnAccessProtection" -Value 1 -Type DWord -Force
Set-ItemProperty -Path $rtpPath -Name "DisableScanOnRealtimeEnable" -Value 1 -Type DWord -Force

Write-Host "Windows Defender disabled via registry"

# ------------------------------------------------------------------------------
# Clean up temp files
# ------------------------------------------------------------------------------
Write-Host "=== Cleaning up temp files ==="

Remove-Item -Path "C:\Windows\Temp\*" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -Path "$env:TEMP\*" -Recurse -Force -ErrorAction SilentlyContinue

Stop-Service -Name wuauserv -Force -ErrorAction SilentlyContinue
Remove-Item -Path "C:\Windows\SoftwareDistribution\Download\*" -Recurse -Force -ErrorAction SilentlyContinue
Start-Service -Name wuauserv -ErrorAction SilentlyContinue

Remove-Item -Path "C:\Windows\Prefetch\*" -Force -ErrorAction SilentlyContinue

wevtutil cl Application 2>$null
wevtutil cl Security 2>$null
wevtutil cl System 2>$null

Write-Host "Temp files cleaned"

# ------------------------------------------------------------------------------
# Run GCESysprep
# This MUST be the last step - it generalizes the image and shuts down the VM,
# which is the signal Packer waits for before capturing the image.
# ------------------------------------------------------------------------------
Write-Host "=== Running GCESysprep ==="
Write-Host "Instance will shut down after sysprep..."

$gceSysprepBat = "C:\Program Files\Google\Compute Engine\sysprep\gcesysprep.bat"

if (Test-Path $gceSysprepBat) {
    & $gceSysprepBat
} elseif (Get-Command GCESysprep -ErrorAction SilentlyContinue) {
    GCESysprep
} else {
    Write-Error "GCESysprep not found - is the Google Compute Engine agent installed on the source image?"
    exit 1
}
