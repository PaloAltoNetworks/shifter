# Install vulnerable services for Windows victim AMI
# XAMPP, IIS, FTP Server, OpenSSH Server
$ErrorActionPreference = "Stop"

Write-Host "=== Installing services ==="

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

# ------------------------------------------------------------------------------
# OpenSSH Server
# ------------------------------------------------------------------------------
Write-Host "=== Installing OpenSSH Server ==="

# Install OpenSSH Server capability
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0

# Configure sshd service
Set-Service -Name sshd -StartupType Automatic

# Set default shell to PowerShell
New-ItemProperty -Path "HKLM:\SOFTWARE\OpenSSH" -Name DefaultShell -Value "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -PropertyType String -Force

# Ensure ssh-agent is available
Set-Service -Name ssh-agent -StartupType Automatic -ErrorAction SilentlyContinue

Write-Host "OpenSSH Server installed and configured"

Write-Host "=== Services installation complete ==="
