#!/bin/bash
set -euo pipefail

# Log output
exec > >(tee /var/log/user-data.log) 2>&1
echo "Victim Linux instance booting..."

# Set hostname from scenario template
echo "Setting hostname to ${hostname}..."
hostnamectl set-hostname ${hostname}
echo "127.0.0.1 ${hostname}" >> /etc/hosts
echo "Hostname set"

# All setup (SSH, XDR) is handled by Ansible playbooks:
#   - range_linux_setup.yml: SSH, XDR agent installation
# This keeps user_data minimal and testable.

echo "user_data complete. Ansible will handle remaining setup."
