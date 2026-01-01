# Install development tools for Windows victim AMI
# Python, Node.js, Git
$ErrorActionPreference = "Stop"

Write-Host "=== Installing development tools ==="

# ------------------------------------------------------------------------------
# Python
# ------------------------------------------------------------------------------
Write-Host "=== Installing Python ==="

$pythonVersion = "3.12.1"
$pythonInstaller = "python-$pythonVersion-amd64.exe"
$pythonUrl = "https://www.python.org/ftp/python/$pythonVersion/$pythonInstaller"

# Download Python
Write-Host "Downloading Python $pythonVersion..."
Invoke-WebRequest -Uri $pythonUrl -OutFile "C:\Windows\Temp\$pythonInstaller" -UseBasicParsing

# Install Python silently with PATH
Write-Host "Installing Python..."
Start-Process -FilePath "C:\Windows\Temp\$pythonInstaller" -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_pip=1" -Wait -NoNewWindow

# Clean up
Remove-Item -Path "C:\Windows\Temp\$pythonInstaller" -Force -ErrorAction SilentlyContinue

Write-Host "Python installed"

# ------------------------------------------------------------------------------
# Node.js
# ------------------------------------------------------------------------------
Write-Host "=== Installing Node.js ==="

$nodeVersion = "20.10.0"
$nodeInstaller = "node-v$nodeVersion-x64.msi"
$nodeUrl = "https://nodejs.org/dist/v$nodeVersion/$nodeInstaller"
$nodePath = "C:\Program Files\nodejs"

# Download Node.js
Write-Host "Downloading Node.js $nodeVersion..."
Invoke-WebRequest -Uri $nodeUrl -OutFile "C:\Windows\Temp\$nodeInstaller" -UseBasicParsing

# Install Node.js silently
Write-Host "Installing Node.js..."
Start-Process -FilePath "msiexec.exe" -ArgumentList "/i `"C:\Windows\Temp\$nodeInstaller`" /quiet /norestart" -Wait -NoNewWindow

# Clean up
Remove-Item -Path "C:\Windows\Temp\$nodeInstaller" -Force -ErrorAction SilentlyContinue

# Refresh environment to get npm in PATH
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

Write-Host "Node.js installed to $nodePath"

# ------------------------------------------------------------------------------
# Git
# ------------------------------------------------------------------------------
Write-Host "=== Installing Git ==="

$gitVersion = "2.43.0"
$gitInstaller = "Git-$gitVersion-64-bit.exe"
$gitUrl = "https://github.com/git-for-windows/git/releases/download/v$gitVersion.windows.1/$gitInstaller"

# Download Git
Write-Host "Downloading Git $gitVersion..."
Invoke-WebRequest -Uri $gitUrl -OutFile "C:\Windows\Temp\$gitInstaller" -UseBasicParsing

# Install Git silently
Write-Host "Installing Git..."
Start-Process -FilePath "C:\Windows\Temp\$gitInstaller" -ArgumentList "/VERYSILENT /NORESTART /NOCANCEL /SP- /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS /COMPONENTS=`"icons,ext\reg\shellhere,assoc,assoc_sh`"" -Wait -NoNewWindow

# Clean up
Remove-Item -Path "C:\Windows\Temp\$gitInstaller" -Force -ErrorAction SilentlyContinue

# Refresh environment
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

Write-Host "Git installed"

Write-Host "=== Development tools installation complete ==="
