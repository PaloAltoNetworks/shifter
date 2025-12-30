#!/bin/bash
# Base packages and SSM agent for Kali AMI
set -euo pipefail

echo "=== Updating package lists ==="
export DEBIAN_FRONTEND=noninteractive
apt-get update

echo "=== Installing base packages ==="
apt-get install -y \
  curl \
  wget \
  git \
  unzip \
  jq \
  htop \
  tmux \
  vim

echo "=== Installing SSM Agent ==="
# SSM agent not in Kali repos - install from AWS
cd /tmp
wget -q https://s3.amazonaws.com/ec2-downloads-windows/SSMAgent/latest/debian_amd64/amazon-ssm-agent.deb
dpkg -i amazon-ssm-agent.deb
systemctl enable amazon-ssm-agent

echo "=== Base setup complete ==="
