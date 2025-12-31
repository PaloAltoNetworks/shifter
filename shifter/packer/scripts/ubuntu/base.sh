#!/bin/bash
# Base packages and SSM agent for Ubuntu victim AMI
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

echo "=== Updating package lists ==="
apt-get update

echo "=== Upgrading system packages ==="
apt-get upgrade -y

echo "=== Installing SSM Agent ==="
# SSM agent for AWS Systems Manager
snap install amazon-ssm-agent --classic
systemctl enable snap.amazon-ssm-agent.amazon-ssm-agent.service

echo "=== Base setup complete ==="
