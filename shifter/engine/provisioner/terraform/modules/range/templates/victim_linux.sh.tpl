#!/bin/bash
set -euo pipefail

# Log output
exec > >(tee /var/log/user-data.log) 2>&1
echo "Victim Linux instance booting..."

# Pin DNS so the SSM agent can register (issue #1632). Injected from the
# range module's linux_range_dns_pin local so the logic lives in one place.
${dns_pin}
# Set hostname from scenario template
echo "Setting hostname to ${hostname}..."
hostnamectl set-hostname ${hostname}
echo "127.0.0.1 ${hostname}" >> /etc/hosts
echo "Hostname set"

# Issue #762: the per-instance ubuntu desktop password is set by the
# engine provisioner via SSM Run Command after this instance reports
# SSMAvailable — not in user_data. The password value never appears
# in EC2 user_data, IMDS, or process argv on this host. See
# shifter/engine/provisioner/plans/set_local_password_plan.py.

# All other setup (SSH, XDR) is handled by Ansible playbooks:
#   - range_linux_setup.yml: SSH, XDR agent installation
# This keeps user_data minimal and testable.

echo "user_data complete. Ansible will handle remaining setup."
