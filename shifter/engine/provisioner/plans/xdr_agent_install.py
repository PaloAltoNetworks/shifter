"""XDR Agent installation plan for Windows instances.

TODO: Delete after Ansible debugging - merged into ansible/playbooks/range_windows_setup.yml and range_dc_setup.yml

Defines the steps to download and install Cortex XDR agent on Windows
instances via SSM Run Command.
"""

from typing import Any, ClassVar

from .base import SetupStep

# PowerShell script to download XDR agent from S3 presigned URL
DOWNLOAD_XDR_SCRIPT = """
$ErrorActionPreference = "Stop"

$presignedUrl = "{{ agent_presigned_url }}"
$installerPath = "C:\\Windows\\Temp\\cortex_xdr_installer.msi"
$maxRetries = 5
$retryDelaySeconds = 10

Write-Host "Downloading XDR agent installer..."

# Cleanup any existing file from previous attempts (prevents file lock issues)
if (Test-Path $installerPath) {
    Write-Host "Removing existing installer file..."
    Remove-Item $installerPath -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

# Extract hostname from presigned URL for diagnostics
$uri = [System.Uri]$presignedUrl
$s3Host = $uri.Host
Write-Host "S3 endpoint: $s3Host"

# Test DNS resolution
Write-Host "Testing DNS resolution..."
try {
    $dns = [System.Net.Dns]::GetHostAddresses($s3Host)
    Write-Host "DNS resolved to: $($dns -join ', ')"
} catch {
    Write-Host "WARNING: DNS resolution failed: $_"
}

# Ensure TLS 1.2+ for S3 presigned URLs
$tls = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13
[Net.ServicePointManager]::SecurityProtocol = $tls
Write-Host "TLS protocols enabled: $([Net.ServicePointManager]::SecurityProtocol)"

# Download with retry logic
$lastError = $null
for ($attempt = 1; $attempt -le $maxRetries; $attempt++) {
    try {
        Write-Host "Download attempt $attempt of $maxRetries at $(Get-Date -Format 'HH:mm:ss')..."
        $startTime = Get-Date
        Invoke-WebRequest -Uri $presignedUrl -OutFile $installerPath -UseBasicParsing -TimeoutSec 120
        $duration = (Get-Date) - $startTime
        Write-Host "Download completed in $($duration.TotalSeconds) seconds"

        if (Test-Path $installerPath) {
            $fileSize = (Get-Item $installerPath).Length
            if ($fileSize -gt 0) {
                Write-Host "Download complete: $installerPath ($fileSize bytes)"
                exit 0
            } else {
                throw "Downloaded file is empty"
            }
        } else {
            throw "Failed to download installer - file not found"
        }
    } catch {
        $lastError = $_
        Write-Host "Attempt $attempt failed: $_"
        Write-Host "Exception type: $($_.Exception.GetType().FullName)"
        if ($_.Exception.InnerException) {
            Write-Host "Inner exception: $($_.Exception.InnerException.Message)"
        }

        if ($attempt -lt $maxRetries) {
            # Exponential backoff: 10s, 20s, 40s, 80s
            $delay = $retryDelaySeconds * [Math]::Pow(2, $attempt - 1)
            Write-Host "Retrying in $delay seconds..."
            Start-Sleep -Seconds $delay
            # Cleanup partial download
            if (Test-Path $installerPath) {
                Remove-Item $installerPath -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

Write-Host "All $maxRetries download attempts failed"
Write-Host "Last error: $lastError"
exit 1
"""

# PowerShell script to install XDR agent silently
INSTALL_XDR_SCRIPT = """
$ErrorActionPreference = "Stop"

$installerPath = "C:\\Windows\\Temp\\cortex_xdr_installer.msi"

Write-Host "Installing Cortex XDR agent..."

try {
    if (-not (Test-Path $installerPath)) {
        throw "Installer not found at $installerPath"
    }

    # Run MSI installer silently
    $process = Start-Process msiexec.exe -ArgumentList "/i", $installerPath, "/qn", "/norestart" -Wait -PassThru

    if ($process.ExitCode -eq 0) {
        Write-Host "XDR agent installed successfully"
    } elseif ($process.ExitCode -eq 3010) {
        Write-Host "XDR agent installed, reboot may be required"
    } else {
        throw "MSI install failed with exit code: $($process.ExitCode)"
    }

    # Cleanup installer
    Remove-Item $installerPath -Force -ErrorAction SilentlyContinue
    Write-Host "Installer cleanup complete"

    exit 0
} catch {
    Write-Host "Error installing XDR agent: $_"
    exit 1
}
"""

# PowerShell script to verify XDR agent is running
VERIFY_XDR_SCRIPT = """
$ErrorActionPreference = "Stop"

Write-Host "Verifying Cortex XDR agent..."

try {
    # Check for CortexXDR service (main service name)
    $service = Get-Service -Name "CortexXDR" -ErrorAction SilentlyContinue
    if ($service -and $service.Status -eq "Running") {
        Write-Host "Cortex XDR service is running"
        exit 0
    }

    # Check alternative service names (cyserver is common)
    $altService = Get-Service -Name "cyserver" -ErrorAction SilentlyContinue
    if ($altService -and $altService.Status -eq "Running") {
        Write-Host "Cortex XDR service (cyserver) is running"
        exit 0
    }

    # Check for Traps/XDR agent process
    $xdrProcess = Get-Process -Name "CortexXDR*" -ErrorAction SilentlyContinue
    if ($xdrProcess) {
        Write-Host "Cortex XDR process found: $($xdrProcess.Name)"
        exit 0
    }

    # If no service or process found, agent may still be initializing
    Write-Host "XDR agent service/process not found - agent may still be initializing"
    exit 1
} catch {
    Write-Host "Error verifying XDR agent: $_"
    exit 1
}
"""


class XDRAgentInstallPlan:
    """Setup plan for installing Cortex XDR agent on Windows instances.

    This plan runs AFTER DC setup completes (parallel with domain member joins).
    It downloads and installs the XDR agent from the user's uploaded installer.

    Steps:
    1. Download installer from S3 presigned URL
    2. Install MSI silently

    Verification:
    - Check XDR service is running
    """

    steps: ClassVar[list[SetupStep]] = [
        SetupStep(
            name="download_xdr_agent",
            script=DOWNLOAD_XDR_SCRIPT,
            timeout_seconds=300,  # 5 min for download
        ),
        SetupStep(
            name="install_xdr_agent",
            script=INSTALL_XDR_SCRIPT,
            timeout_seconds=600,  # 10 min for install
        ),
    ]

    verify_step: ClassVar[SetupStep] = SetupStep(
        name="verify_xdr_agent",
        script=VERIFY_XDR_SCRIPT,
        timeout_seconds=120,  # 2 min for verification
        is_verification=True,
    )

    def get_context(self, config: dict[str, Any]) -> dict[str, Any]:
        """Get template variables for XDR install scripts.

        Args:
            config: Dict with agent_presigned_url

        Returns:
            Dict with agent_presigned_url

        Raises:
            ValueError: If agent_presigned_url is missing or empty
        """
        url = config.get("agent_presigned_url")
        if not url:
            raise ValueError("config missing required key 'agent_presigned_url' for XDR install")

        return {"agent_presigned_url": url}
