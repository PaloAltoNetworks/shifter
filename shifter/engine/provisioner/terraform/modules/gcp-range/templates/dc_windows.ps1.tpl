<powershell>
$ErrorActionPreference = "Stop"
$LogFile = "C:\Windows\Temp\gcp-dc-startup.log"

function Log-Message {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$timestamp - $Message" | Out-File -FilePath $LogFile -Append
    Write-Host $Message
}

Log-Message "Starting DC startup script"
Rename-Computer -NewName "${hostname}" -Force
net user Administrator "${admin_password}"

$sshDir = "C:\ProgramData\ssh"
$authKeys = Join-Path $sshDir "administrators_authorized_keys"
if (Test-Path $sshDir) {
    if (-not (Test-Path $authKeys)) {
        New-Item -ItemType File -Path $authKeys -Force | Out-Null
    }
    $publicKey = "${public_key}"
    $existing = Get-Content $authKeys -ErrorAction SilentlyContinue
    if ($existing -notcontains $publicKey) {
        Add-Content -Path $authKeys -Value $publicKey
    }
}

Log-Message "DC startup script complete"
</powershell>
