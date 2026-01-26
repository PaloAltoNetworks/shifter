# Install development tools for Windows victim AMI
# Python, Node.js, Git
$ErrorActionPreference = "Stop"

Write-Host "=== Installing development tools ==="

# ------------------------------------------------------------------------------
# Python (using winget for reliability)
# ------------------------------------------------------------------------------
Write-Host "=== Installing Python ==="

# Try winget first (more reliable), fall back to direct download
$wingetPath = Get-Command winget -ErrorAction SilentlyContinue
if ($wingetPath) {
    Write-Host "Installing Python via winget..."
    winget install Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
} else {
    Write-Host "winget not available, downloading Python directly..."
    $pythonVersion = "3.12.4"
    $pythonInstaller = "python-$pythonVersion-amd64.exe"
    $pythonUrl = "https://www.python.org/ftp/python/$pythonVersion/$pythonInstaller"

    Invoke-WebRequest -Uri $pythonUrl -OutFile "C:\Windows\Temp\$pythonInstaller" -UseBasicParsing
    Start-Process -FilePath "C:\Windows\Temp\$pythonInstaller" -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_pip=1" -Wait -NoNewWindow
    Remove-Item -Path "C:\Windows\Temp\$pythonInstaller" -Force -ErrorAction SilentlyContinue
}

Write-Host "Python installed"

# ------------------------------------------------------------------------------
# Node.js LTS
# ------------------------------------------------------------------------------
Write-Host "=== Installing Node.js ==="

$nodePath = "C:\Program Files\nodejs"

if ($wingetPath) {
    Write-Host "Installing Node.js via winget..."
    winget install OpenJS.NodeJS.LTS --silent --accept-package-agreements --accept-source-agreements
} else {
    Write-Host "winget not available, downloading Node.js directly..."
    $nodeVersion = "20.11.1"
    $nodeInstaller = "node-v$nodeVersion-x64.msi"
    $nodeUrl = "https://nodejs.org/dist/v$nodeVersion/$nodeInstaller"

    Invoke-WebRequest -Uri $nodeUrl -OutFile "C:\Windows\Temp\$nodeInstaller" -UseBasicParsing
    Start-Process -FilePath "msiexec.exe" -ArgumentList "/i `"C:\Windows\Temp\$nodeInstaller`" /quiet /norestart" -Wait -NoNewWindow
    Remove-Item -Path "C:\Windows\Temp\$nodeInstaller" -Force -ErrorAction SilentlyContinue
}

# Refresh environment to get npm in PATH
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

Write-Host "Node.js installed"

# ------------------------------------------------------------------------------
# Git
# ------------------------------------------------------------------------------
Write-Host "=== Installing Git ==="

if ($wingetPath) {
    Write-Host "Installing Git via winget..."
    winget install Git.Git --silent --accept-package-agreements --accept-source-agreements
} else {
    Write-Host "winget not available, downloading Git directly..."
    $gitVersion = "2.44.0"
    $gitInstaller = "Git-$gitVersion-64-bit.exe"
    $gitUrl = "https://github.com/git-for-windows/git/releases/download/v$gitVersion.windows.1/$gitInstaller"

    Invoke-WebRequest -Uri $gitUrl -OutFile "C:\Windows\Temp\$gitInstaller" -UseBasicParsing
    Start-Process -FilePath "C:\Windows\Temp\$gitInstaller" -ArgumentList "/VERYSILENT /NORESTART /NOCANCEL /SP- /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS /COMPONENTS=`"icons,ext\reg\shellhere,assoc,assoc_sh`"" -Wait -NoNewWindow
    Remove-Item -Path "C:\Windows\Temp\$gitInstaller" -Force -ErrorAction SilentlyContinue
}

# Refresh environment
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

Write-Host "Git installed"

Write-Host "=== Development tools installation complete ==="
