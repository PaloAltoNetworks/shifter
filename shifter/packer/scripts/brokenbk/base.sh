#!/bin/bash
# Base packages and SSM agent for Cortex Broken Bank AMI
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

echo "=== Updating package lists ==="
apt-get update

echo "=== Upgrading system packages ==="
apt-get upgrade -y

echo "=== Updating snapd to patch CVE-2024-24790 ==="
apt-get install -y --only-upgrade snapd
snap refresh

echo "=== Installing SSM Agent ==="
# SSM agent for AWS Systems Manager
snap install amazon-ssm-agent --classic
systemctl enable snap.amazon-ssm-agent.amazon-ssm-agent.service

echo "=== Base setup complete ==="
