"""Linux bootstrap setup plan.

Defines the steps to configure a generic Linux victim instance:
- Set hostname for XDR console visibility
- Configure SSH for browser-based terminal access from Shifter

This plan supports different Linux distributions by using a configurable
SSH user (ubuntu, ec2-user, etc.).
"""

from typing import Any, ClassVar

from .base import SetupStep

# Bash script to set hostname
SET_HOSTNAME_SCRIPT = """#!/bin/bash
set -euo pipefail

hostname="{{ hostname }}"

echo "Setting hostname to $hostname..."

# Set hostname persistently
hostnamectl set-hostname "$hostname"

# Update /etc/hosts
echo "127.0.0.1 $hostname" >> /etc/hosts

echo "Hostname set to $hostname"
exit 0
"""

# Bash script to configure SSH with authorized keys
# Uses template variable for configurable user
CONFIGURE_SSH_SCRIPT = """#!/bin/bash
set -euo pipefail

ssh_user="{{ ssh_user }}"
public_key="{{ public_key }}"

echo "Configuring SSH access for $ssh_user user..."

# Get home directory for user
user_home=$(eval echo ~$ssh_user)

# Create .ssh directory if it doesn't exist
mkdir -p "$user_home/.ssh"
chmod 700 "$user_home/.ssh"

# Add public key to authorized_keys
if [ -n "$public_key" ]; then
    echo "$public_key" >> "$user_home/.ssh/authorized_keys"
    chmod 600 "$user_home/.ssh/authorized_keys"
    chown -R "$ssh_user:$ssh_user" "$user_home/.ssh"
    echo "SSH key authentication configured for $ssh_user user"
else
    echo "No public key provided, skipping key auth setup"
fi

echo "SSH configuration complete"
exit 0
"""

# Bash script to verify hostname is set correctly
VERIFY_HOSTNAME_SCRIPT = """#!/bin/bash
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
"""


class LinuxBootstrapPlan:
    """Bootstrap plan for Linux victim instances.

    This plan configures a Linux instance with:
    1. Hostname for XDR console visibility
    2. SSH access for browser-based terminal

    Supports different SSH users for different distributions:
    - ubuntu: Ubuntu
    - ec2-user: Amazon Linux

    Steps:
    1. Set hostname (no reboot required on Linux)
    2. Configure SSH with authorized keys

    Verification:
    - Check hostname matches expected value
    """

    steps: ClassVar[list[SetupStep]] = [
        SetupStep(
            name="set_hostname",
            script=SET_HOSTNAME_SCRIPT,
            timeout_seconds=60,
            requires_reboot=False,
        ),
        SetupStep(
            name="configure_ssh",
            script=CONFIGURE_SSH_SCRIPT,
            timeout_seconds=60,
            requires_reboot=False,
        ),
    ]

    verify_step: ClassVar[SetupStep] = SetupStep(
        name="verify_hostname",
        script=VERIFY_HOSTNAME_SCRIPT,
        timeout_seconds=30,
        is_verification=True,
    )

    def get_context(self, instance: Any) -> dict[str, Any]:
        """Get template variables for Linux bootstrap scripts.

        Args:
            instance: Instance with hostname, public_key, and ssh_user attributes

        Returns:
            Dict with hostname, public_key, and ssh_user

        Raises:
            ValueError: If hostname is missing or empty
        """
        hostname = getattr(instance, "hostname", None)
        if not hostname:
            raise ValueError("Instance missing required 'hostname' attribute for Linux bootstrap")

        public_key = getattr(instance, "public_key", "")
        ssh_user = getattr(instance, "ssh_user", "ubuntu")  # Default to ubuntu

        return {
            "hostname": hostname,
            "public_key": public_key,
            "ssh_user": ssh_user,
        }
