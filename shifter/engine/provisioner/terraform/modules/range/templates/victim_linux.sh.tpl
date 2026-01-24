#!/bin/bash
set -euo pipefail

# Log output
exec > >(tee /var/log/user-data.log) 2>&1
echo "Victim Linux instance booting..."

# All setup (hostname, SSH, XDR) is handled by Ansible playbooks:
#   - range_linux_setup.yml: hostname, SSH, XDR agent installation
# This keeps user_data minimal and testable.

echo "user_data complete. Ansible will handle remaining setup."
