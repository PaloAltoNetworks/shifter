#!/bin/bash
# Add sshpass to existing Kali AMI
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

echo "=== Installing sshpass ==="
apt-get update
apt-get install -y sshpass

echo "=== Verifying installation ==="
sshpass -V

echo "=== sshpass installed successfully ==="
