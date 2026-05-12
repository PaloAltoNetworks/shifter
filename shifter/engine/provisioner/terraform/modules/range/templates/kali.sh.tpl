#!/bin/bash
set -euo pipefail

# Log output
exec > >(tee /var/log/user-data.log) 2>&1
echo "Starting Kali headless setup..."

# Set hostname for XDR console visibility
echo "Setting hostname to ${hostname}..."
hostnamectl set-hostname ${hostname}
echo "127.0.0.1 ${hostname}" >> /etc/hosts
echo "Hostname set"

# Configure SSH access for MCP server.
# The chown is `|| true` so this template stays compatible with non-Kali
# AMIs (e.g., the polaris VM is an Ubuntu host running the Kali container
# under docker; the host has no `kali` user, so the chown legitimately
# fails — the actual /home/kali authorized_keys lives inside the container
# and is set by a separate post-boot plan). On a real Kali AMI the kali
# user does exist and chown succeeds, so the `|| true` is a no-op.
echo "Configuring SSH access..."
mkdir -p /home/kali/.ssh
chmod 700 /home/kali/.ssh
echo "${public_key}" >> /home/kali/.ssh/authorized_keys
chmod 600 /home/kali/.ssh/authorized_keys
chown -R kali:kali /home/kali/.ssh 2>/dev/null || echo "kali user not present on host (likely a containerized Kali stack); skipping chown"
echo "SSH access configured"

# Issue #762: the per-instance kali desktop password is set by the
# engine provisioner via SSM Run Command after this instance reports
# SSMAvailable — not in user_data. The password value never appears
# in EC2 user_data, IMDS, or process argv on this host. See
# shifter/engine/provisioner/plans/set_local_password_plan.py.

# Ensure xrdp is running for RDP access via Guacamole. Same compatibility
# story as the chown above — a containerized-Kali AMI has no host xrdp
# unit and this systemctl call legitimately fails.
echo "Starting xrdp service..."
if systemctl list-unit-files xrdp.service >/dev/null 2>&1; then
    systemctl start xrdp
    systemctl status xrdp --no-pager || true
    echo "xrdp service started"
else
    echo "xrdp.service not present on host (likely a containerized Kali stack); skipping"
fi

echo "Kali setup complete"
