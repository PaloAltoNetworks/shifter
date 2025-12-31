# Sysprep preparation for Windows victim AMI
# Disable problematic services, clean up, and run EC2Launch sysprep
$ErrorActionPreference = "Stop"

Write-Host "=== Preparing for sysprep ==="

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

# Create the key if it doesn't exist
if (-not (Test-Path $defenderPath)) {
    New-Item -Path $defenderPath -Force | Out-Null
}

# Disable Windows Defender
Set-ItemProperty -Path $defenderPath -Name "DisableAntiSpyware" -Value 1 -Type DWord -Force
Set-ItemProperty -Path $defenderPath -Name "DisableAntiVirus" -Value 1 -Type DWord -Force

# Disable real-time protection
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

# Clear Windows temp
Remove-Item -Path "C:\Windows\Temp\*" -Recurse -Force -ErrorAction SilentlyContinue

# Clear user temp
Remove-Item -Path "$env:TEMP\*" -Recurse -Force -ErrorAction SilentlyContinue

# Clear Windows Update cache
Stop-Service -Name wuauserv -Force -ErrorAction SilentlyContinue
Remove-Item -Path "C:\Windows\SoftwareDistribution\Download\*" -Recurse -Force -ErrorAction SilentlyContinue
Start-Service -Name wuauserv -ErrorAction SilentlyContinue

# Clear prefetch
Remove-Item -Path "C:\Windows\Prefetch\*" -Force -ErrorAction SilentlyContinue

# Clear event logs (optional - keeps AMI clean)
wevtutil cl Application 2>$null
wevtutil cl Security 2>$null
wevtutil cl System 2>$null

Write-Host "Temp files cleaned"

# ------------------------------------------------------------------------------
# Run EC2Launch sysprep
# This MUST be the last step - it shuts down the instance
# ------------------------------------------------------------------------------
Write-Host "=== Running EC2Launch sysprep ==="
Write-Host "Instance will shut down after sysprep..."

# EC2Launch v2 sysprep command
$ec2LaunchPath = "C:\Program Files\Amazon\EC2Launch\EC2Launch.exe"

if (Test-Path $ec2LaunchPath) {
    & $ec2LaunchPath sysprep --shutdown
} else {
    Write-Error "EC2Launch not found at $ec2LaunchPath"
    exit 1
}
