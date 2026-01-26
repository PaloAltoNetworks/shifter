# Install services for Windows AMI (victim or DC)
# Victim: XAMPP, IIS, FTP Server, OpenSSH Server
# DC: OpenSSH Server only
#
# Usage:
#   .\services.ps1           - Victim configuration (default)
#   .\services.ps1 -Role dc  - Domain Controller configuration
#   PACKER_ROLE=dc           - Environment variable (used by Packer)
param(
    [ValidateSet("victim", "dc")]
    [string]$Role = ""
)

# If no parameter provided, check environment variable (set by Packer)
if (-not $Role) {
    $Role = if ($env:PACKER_ROLE) { $env:PACKER_ROLE } else { "victim" }
}

$ErrorActionPreference = "Stop"

Write-Host "=== Installing services (Role: $Role) ==="

if ($Role -eq "victim") {
    # ------------------------------------------------------------------------------
    # XAMPP (Apache, MySQL, PHP)
    # ------------------------------------------------------------------------------
    Write-Host "=== Installing XAMPP ==="

    $xamppVersion = "8.2.12"
    $xamppInstaller = "xampp-windows-x64-$xamppVersion-0-VS16-installer.exe"
    $xamppUrl = "https://sourceforge.net/projects/xampp/files/XAMPP%20Windows/$xamppVersion/$xamppInstaller/download"
    $xamppPath = "C:\xampp"

    # Download XAMPP
    Write-Host "Downloading XAMPP $xamppVersion..."
    $webClient = New-Object System.Net.WebClient
    $webClient.DownloadFile($xamppUrl, "C:\Windows\Temp\$xamppInstaller")

    # Install XAMPP silently
    Write-Host "Installing XAMPP..."
    Start-Process -FilePath "C:\Windows\Temp\$xamppInstaller" -ArgumentList "--mode unattended --launchapps 0" -Wait -NoNewWindow

    # Configure XAMPP services to start automatically
    if (Test-Path "$xamppPath\apache\bin\httpd.exe") {
        # Install Apache as a service
        Start-Process -FilePath "$xamppPath\apache\bin\httpd.exe" -ArgumentList "-k install" -Wait -NoNewWindow -ErrorAction SilentlyContinue
        Set-Service -Name "Apache2.4" -StartupType Automatic -ErrorAction SilentlyContinue
        Write-Host "Apache installed as service"
    }

    if (Test-Path "$xamppPath\mysql\bin\mysqld.exe") {
        # Install MySQL as a service
        Start-Process -FilePath "$xamppPath\mysql\bin\mysqld.exe" -ArgumentList "--install MySQL --defaults-file=`"$xamppPath\mysql\bin\my.ini`"" -Wait -NoNewWindow -ErrorAction SilentlyContinue
        Set-Service -Name "MySQL" -StartupType Automatic -ErrorAction SilentlyContinue
        Write-Host "MySQL installed as service"
    }

    # Clean up installer
    Remove-Item -Path "C:\Windows\Temp\$xamppInstaller" -Force -ErrorAction SilentlyContinue

    Write-Host "XAMPP installed to $xamppPath"

    # ------------------------------------------------------------------------------
    # IIS (Internet Information Services)
    # ------------------------------------------------------------------------------
    Write-Host "=== Installing IIS ==="

    # Install IIS with management tools
    Install-WindowsFeature -Name Web-Server -IncludeManagementTools -ErrorAction Stop
    Install-WindowsFeature -Name Web-Asp-Net45 -ErrorAction SilentlyContinue
    Install-WindowsFeature -Name Web-Net-Ext45 -ErrorAction SilentlyContinue
    Install-WindowsFeature -Name Web-ISAPI-Ext -ErrorAction SilentlyContinue
    Install-WindowsFeature -Name Web-ISAPI-Filter -ErrorAction SilentlyContinue

    # Ensure IIS service starts automatically
    Set-Service -Name "W3SVC" -StartupType Automatic

    Write-Host "IIS installed with management tools"

    # ------------------------------------------------------------------------------
    # FTP Server
    # ------------------------------------------------------------------------------
    Write-Host "=== Installing FTP Server ==="

    # Install FTP Server feature
    Install-WindowsFeature -Name Web-Ftp-Server -IncludeAllSubFeature -ErrorAction Stop

    # Configure FTP service to start automatically
    Set-Service -Name "FTPSVC" -StartupType Automatic -ErrorAction SilentlyContinue

    Write-Host "FTP Server installed"
}

# ------------------------------------------------------------------------------
# OpenSSH Server (both victim and DC)
# ------------------------------------------------------------------------------
Write-Host "=== Installing OpenSSH Server ==="

# Check if OpenSSH Server is already installed
$sshCapability = Get-WindowsCapability -Online | Where-Object { $_.Name -like "OpenSSH.Server*" }
if ($sshCapability.State -eq "Installed") {
    Write-Host "OpenSSH Server already installed"
} else {
    Write-Host "Installing OpenSSH Server capability..."
    try {
        Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 -ErrorAction Stop
        Write-Host "OpenSSH Server capability installed via PowerShell"
    } catch {
        Write-Host "WARNING: Add-WindowsCapability failed: $($_.Exception.Message)"
        Write-Host "Attempting DISM fallback..."
        $dismResult = dism /Online /Add-Capability /CapabilityName:OpenSSH.Server~~~~0.0.1.0 /NoRestart 2>&1
        Write-Host $dismResult
    }

    # Verify installation succeeded
    $sshCapability = Get-WindowsCapability -Online | Where-Object { $_.Name -like "OpenSSH.Server*" }
    if ($sshCapability.State -ne "Installed") {
        Write-Error "FATAL: OpenSSH Server installation failed - SSH is required"
        exit 1
    }
    Write-Host "OpenSSH Server installation verified"
}

# Configure sshd service (only if it exists)
$sshdService = Get-Service -Name sshd -ErrorAction SilentlyContinue
if ($sshdService) {
    Set-Service -Name sshd -StartupType Automatic
    Write-Host "sshd service configured"
} else {
    Write-Host "WARNING: sshd service not found"
}

# Set default shell to PowerShell (create key if needed)
$openSSHKeyPath = "HKLM:\SOFTWARE\OpenSSH"
if (-not (Test-Path $openSSHKeyPath)) {
    New-Item -Path $openSSHKeyPath -Force | Out-Null
}
New-ItemProperty -Path $openSSHKeyPath -Name DefaultShell -Value "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -PropertyType String -Force | Out-Null
Write-Host "Default shell set to PowerShell"

# Enable password authentication for SSH/SFTP
$sshdConfigPath = "C:\ProgramData\ssh\sshd_config"
if (Test-Path $sshdConfigPath) {
    $sshdConfig = Get-Content $sshdConfigPath
    # Enable password authentication
    $sshdConfig = $sshdConfig -replace '^#?PasswordAuthentication\s+.*', 'PasswordAuthentication yes'
    # Ensure it's added if not present
    if ($sshdConfig -notmatch 'PasswordAuthentication') {
        $sshdConfig += "`nPasswordAuthentication yes"
    }
    Set-Content -Path $sshdConfigPath -Value $sshdConfig
    Write-Host "Enabled password authentication in sshd_config"
} else {
    Write-Host "sshd_config not found (SSH may not be fully installed)"
}

# Ensure ssh-agent is available
Set-Service -Name ssh-agent -StartupType Automatic -ErrorAction SilentlyContinue

Write-Host "OpenSSH Server installed and configured"

Write-Host "=== Services installation complete ==="
