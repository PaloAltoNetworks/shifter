#!/bin/bash
# Pre-AMI cleanup to reduce image size
set -euo pipefail

echo "=== Cleaning up ==="

# Clear apt cache
apt-get clean
apt-get autoremove -y
rm -rf /var/lib/apt/lists/*

# Clear temp files
rm -rf /tmp/*
rm -rf /var/tmp/*

# Clear logs
find /var/log -type f -name "*.log" -delete
find /var/log -type f -name "*.gz" -delete
journalctl --vacuum-time=1d 2>/dev/null || true

# Clear bash history
rm -f /root/.bash_history
rm -f /home/*/.bash_history
history -c 2>/dev/null || true

# Clear SSH host keys (will be regenerated on first boot)
rm -f /etc/ssh/ssh_host_*

echo "=== Cleanup complete ==="
