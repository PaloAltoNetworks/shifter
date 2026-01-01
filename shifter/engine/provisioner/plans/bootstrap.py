"""Bootstrap setup plan.

Handles initial instance configuration that all instances need:
- Hostname setting
- SSH key configuration

This plan runs before any role-specific plans (DC, victim, etc.)
Currently Windows-only. Linux support can be added later.
"""

from typing import Any, Dict, List

from .base import SetupStep


# PowerShell script to set hostname and reboot
SET_HOSTNAME_SCRIPT = '''
$ErrorActionPreference = "Stop"
$hostname = "{{ hostname }}"

Write-Host "Setting hostname to $hostname..."

try {
    Rename-Computer -NewName $hostname -Force -ErrorAction Stop
    Write-Host "Hostname set to $hostname - reboot required"
    exit 0
} catch {
    Write-Host "Error setting hostname: $_"
    exit 1
}
'''

# PowerShell script to configure SSH with public key
CONFIGURE_SSH_SCRIPT = '''
$ErrorActionPreference = "Stop"
$publicKey = "{{ public_key }}"

Write-Host "Configuring OpenSSH Server..."

try {
    # Ensure SSH server is running
    Start-Service sshd -ErrorAction Stop
    Set-Service -Name sshd -StartupType Automatic
    Write-Host "SSH service started and set to automatic"

    # Set up SSH key authentication for Administrator
    if ($publicKey) {
        $sshDir = "C:\\ProgramData\\ssh"
        if (!(Test-Path $sshDir)) {
            New-Item -ItemType Directory -Path $sshDir -Force | Out-Null
        }

        $publicKey | Out-File -Encoding ascii "$sshDir\\administrators_authorized_keys"

        # Set proper permissions
        icacls "$sshDir\\administrators_authorized_keys" /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F" | Out-Null

        Write-Host "SSH key authentication configured"
    } else {
        Write-Host "No public key provided, skipping key auth setup"
    }

    Write-Host "SSH configuration complete"
    exit 0
} catch {
    Write-Host "Error configuring SSH: $_"
    exit 1
}
'''


class BootstrapPlan:
    """Bootstrap plan for initial Windows instance configuration.

    Steps:
    1. Set hostname (requires reboot)
    2. Configure SSH

    This plan should run before any role-specific plans.
    """

    steps: List[SetupStep] = [
        SetupStep(
            name="set_hostname",
            script=SET_HOSTNAME_SCRIPT,
            timeout_seconds=600,  # 10 min - generous for first boot SSM latency
            requires_reboot=True,
        ),
        SetupStep(
            name="configure_ssh",
            script=CONFIGURE_SSH_SCRIPT,
            timeout_seconds=600,  # 10 min - generous for post-reboot SSM latency
            requires_reboot=False,
        ),
    ]

    # No verification step - bootstrap success is implicit if steps complete
    verify_step: SetupStep = None

    def get_context(self, instance: Any) -> Dict[str, Any]:
        """Get template variables for bootstrap scripts.

        Args:
            instance: Instance with hostname and public_key attributes

        Returns:
            Dict with hostname and public_key

        Raises:
            ValueError: If hostname is missing
        """
        hostname = getattr(instance, "hostname", None)
        if not hostname:
            raise ValueError("Instance missing required 'hostname' attribute for bootstrap")

        public_key = getattr(instance, "public_key", "")

        return {
            "hostname": hostname,
            "public_key": public_key,
        }
