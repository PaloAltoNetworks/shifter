#!/bin/bash
# Base packages and SSM agent for Kali AMI
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

echo "=== Updating package lists ==="
apt-get update

echo "=== Installing SSM Agent ==="
# SSM agent not in Kali repos - install from AWS
cd /tmp
wget -q https://s3.amazonaws.com/ec2-downloads-windows/SSMAgent/latest/debian_amd64/amazon-ssm-agent.deb
dpkg -i amazon-ssm-agent.deb
systemctl enable amazon-ssm-agent

echo "=== Installing xrdp for RDP access ==="
apt-get install -y xrdp xorgxrdp
systemctl enable xrdp
# Configure xrdp to use existing desktop session
echo "exec startxfce4" > /home/kali/.xsession
chown kali:kali /home/kali/.xsession

echo "=== Base setup complete ==="
