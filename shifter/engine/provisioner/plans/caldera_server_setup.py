"""Caldera server setup plan.

Defines the steps to start MITRE Caldera adversary emulation server
on the Kali attacker box and make it available to all instances in the range.

This plan is NOT activated by default - it is designed for future integration
with the setup orchestrator when Caldera functionality is enabled.

Caldera is pre-installed on the Kali AMI at /opt/caldera.
Default credentials: red/admin
Default web UI: http://<kali-ip>:8888

Reference: https://github.com/mitre/caldera
"""

from typing import Any, ClassVar

from .base import SetupStep

# Bash script to start Caldera server
# Binds to 0.0.0.0 to be accessible from other range instances
START_CALDERA_SCRIPT = """#!/bin/bash
set -euo pipefail

caldera_dir="/opt/caldera"
caldera_port="{{ caldera_port }}"
caldera_host="{{ caldera_host }}"

echo "Starting MITRE Caldera server..."

# Check if Caldera is installed
if [ ! -d "$caldera_dir" ]; then
    echo "ERROR: Caldera not found at $caldera_dir"
    exit 1
fi

cd "$caldera_dir"

# Check if server is already running
if pgrep -f "python3 server.py" > /dev/null; then
    echo "Caldera server is already running"
    exit 0
fi

# Activate virtual environment and start server in background
# --insecure allows HTTP (no TLS) for internal range use
# Bind to 0.0.0.0 to allow connections from other range instances
source .venv/bin/activate
nohup python3 server.py --insecure --port "$caldera_port" --host "$caldera_host" > /var/log/caldera.log 2>&1 &

# Wait for server to start (up to 60 seconds)
echo "Waiting for Caldera server to start..."
for i in $(seq 1 30); do
    if curl -s "http://localhost:$caldera_port" > /dev/null 2>&1; then
        echo "Caldera server started successfully on port $caldera_port"
        echo "Web UI: http://localhost:$caldera_port"
        echo "Default credentials: red/admin"
        exit 0
    fi
    sleep 2
done

echo "ERROR: Caldera server failed to start within timeout"
exit 1
"""

# Bash script to verify Caldera server is running and accessible
VERIFY_CALDERA_SCRIPT = """#!/bin/bash
set -euo pipefail

caldera_port="{{ caldera_port }}"

echo "Verifying Caldera server is running..."

# Check if process is running
if ! pgrep -f "python3 server.py" > /dev/null; then
    echo "ERROR: Caldera server process not found"
    exit 1
fi

# Check if HTTP endpoint responds
if curl -s --max-time 10 "http://localhost:$caldera_port" > /dev/null 2>&1; then
    echo "Caldera server is running and responding on port $caldera_port"
    exit 0
else
    echo "ERROR: Caldera server not responding on port $caldera_port"
    exit 1
fi
"""

# Bash script to stop Caldera server (for cleanup/shutdown)
STOP_CALDERA_SCRIPT = """#!/bin/bash
set -euo pipefail

echo "Stopping Caldera server..."

if pkill -f "python3 server.py"; then
    echo "Caldera server stopped"
else
    echo "Caldera server was not running"
fi

exit 0
"""


class CalderaServerSetupPlan:
    """Setup plan to start Caldera server on Kali attacker box.

    This plan starts the MITRE Caldera adversary emulation platform
    on the Kali instance, making it available to all other boxes in
    the range for agent deployment.

    NOT ACTIVATED BY DEFAULT - This plan is designed for future use
    when Caldera functionality is integrated into the orchestration flow.

    Prerequisites:
    - Caldera must be pre-installed at /opt/caldera (included in Kali AMI)
    - Instance must be a Kali attacker box

    Steps:
    1. Start Caldera server bound to 0.0.0.0 (all interfaces)

    Verification:
    - Check server process is running
    - Check HTTP endpoint responds

    Context variables:
    - caldera_port: Port to run Caldera on (default: 8888)
    - caldera_host: Host/IP to bind to (default: 0.0.0.0)
    """

    steps: ClassVar[list[SetupStep]] = [
        SetupStep(
            name="start_caldera_server",
            script=START_CALDERA_SCRIPT,
            timeout_seconds=120,
            requires_reboot=False,
        ),
    ]

    verify_step: ClassVar[SetupStep] = SetupStep(
        name="verify_caldera_server",
        script=VERIFY_CALDERA_SCRIPT,
        timeout_seconds=30,
        is_verification=True,
    )

    def get_context(self, instance: Any) -> dict[str, Any]:
        """Get template variables for Caldera server setup scripts.

        Args:
            instance: Instance with optional caldera_port and caldera_host attributes

        Returns:
            Dict with caldera_port and caldera_host
        """
        # Use defaults if not specified on instance
        caldera_port = getattr(instance, "caldera_port", 8888)
        caldera_host = getattr(instance, "caldera_host", "0.0.0.0")

        return {
            "caldera_port": caldera_port,
            "caldera_host": caldera_host,
        }


class CalderaServerStopPlan:
    """Plan to stop Caldera server on Kali attacker box.

    NOT ACTIVATED BY DEFAULT - This plan is designed for future use
    when Caldera functionality is integrated into the orchestration flow.
    """

    steps: ClassVar[list[SetupStep]] = [
        SetupStep(
            name="stop_caldera_server",
            script=STOP_CALDERA_SCRIPT,
            timeout_seconds=30,
            requires_reboot=False,
        ),
    ]

    verify_step: ClassVar[SetupStep | None] = None

    def get_context(self, instance: Any) -> dict[str, Any]:
        """Get template variables (none required for stop)."""
        return {}
