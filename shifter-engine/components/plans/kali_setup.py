"""Kali Linux setup plan.

Defines the steps to configure a Kali Linux attacker instance:
- Set hostname for XDR console visibility
- Configure SSH with authorized keys for portal access

Kali is an attacker instance, so no XDR agent is installed.
"""

from typing import Any, Dict, List

from ..setup_plan import SetupStep


# Bash script to set hostname
SET_HOSTNAME_SCRIPT = '''#!/bin/bash
set -euo pipefail

hostname="{{ hostname }}"

echo "Setting hostname to $hostname..."

# Set hostname persistently
hostnamectl set-hostname "$hostname"

# Update /etc/hosts
echo "127.0.0.1 $hostname" >> /etc/hosts

echo "Hostname set to $hostname"
exit 0
'''

# Bash script to configure SSH with authorized keys
CONFIGURE_SSH_SCRIPT = '''#!/bin/bash
set -euo pipefail

public_key="{{ public_key }}"

echo "Configuring SSH access for kali user..."

# Create .ssh directory if it doesn't exist
mkdir -p /home/kali/.ssh
chmod 700 /home/kali/.ssh

# Add public key to authorized_keys
if [ -n "$public_key" ]; then
    echo "$public_key" >> /home/kali/.ssh/authorized_keys
    chmod 600 /home/kali/.ssh/authorized_keys
    chown -R kali:kali /home/kali/.ssh
    echo "SSH key authentication configured for kali user"
else
    echo "No public key provided, skipping key auth setup"
fi

echo "SSH configuration complete"
exit 0
'''

# Bash script to verify hostname is set correctly
VERIFY_HOSTNAME_SCRIPT = '''#!/bin/bash
set -euo pipefail

expected_hostname="{{ hostname }}"

echo "Verifying hostname configuration..."

current_hostname=$(hostname)

if [ "$current_hostname" = "$expected_hostname" ]; then
    echo "Hostname verified: $current_hostname"
    exit 0
else
    echo "Hostname mismatch!"
    echo "Expected: $expected_hostname"
    echo "Got: $current_hostname"
    exit 1
fi
'''


class KaliSetupPlan:
    """Setup plan for Kali Linux attacker instances.

    This plan configures a Kali instance with:
    1. Hostname for XDR console visibility
    2. SSH access for portal terminal

    No XDR agent is installed (attacker role).

    Steps:
    1. Set hostname (no reboot required on Linux)
    2. Configure SSH with authorized keys

    Verification:
    - Check hostname matches expected value
    """

    steps: List[SetupStep] = [
        SetupStep(
            name="set_hostname",
            script=SET_HOSTNAME_SCRIPT,
            timeout_seconds=60,  # Simple operation, 1 min is plenty
            requires_reboot=False,
        ),
        SetupStep(
            name="configure_ssh",
            script=CONFIGURE_SSH_SCRIPT,
            timeout_seconds=60,  # Simple operation
            requires_reboot=False,
        ),
    ]

    verify_step: SetupStep = SetupStep(
        name="verify_hostname",
        script=VERIFY_HOSTNAME_SCRIPT,
        timeout_seconds=30,
        is_verification=True,
    )

    def get_context(self, instance: Any) -> Dict[str, Any]:
        """Get template variables for Kali setup scripts.

        Args:
            instance: Instance with hostname and public_key attributes

        Returns:
            Dict with hostname and public_key

        Raises:
            ValueError: If hostname is missing or empty
        """
        hostname = getattr(instance, "hostname", None)
        if not hostname:
            raise ValueError("Instance missing required 'hostname' attribute for Kali setup")

        public_key = getattr(instance, "public_key", "")

        return {
            "hostname": hostname,
            "public_key": public_key,
        }
