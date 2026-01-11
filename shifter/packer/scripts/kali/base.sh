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

echo "=== Installing XFCE desktop and xrdp for RDP access ==="
# Install Kali's default XFCE desktop (required for RDP sessions)
apt-get install -y kali-desktop-xfce xrdp xorgxrdp

# Enable xrdp service
systemctl enable xrdp

# Create xrdp log files with correct permissions (fixes "log not initialized" error)
touch /var/log/xrdp.log /var/log/xrdp-sesman.log
chown xrdp:xrdp /var/log/xrdp.log /var/log/xrdp-sesman.log
chmod 640 /var/log/xrdp.log /var/log/xrdp-sesman.log

# Configure xrdp to use XFCE desktop session
echo "exec startxfce4" > /home/kali/.xsession
chown kali:kali /home/kali/.xsession
chmod +x /home/kali/.xsession

# Add kali user to ssl-cert group (required for xrdp)
usermod -aG ssl-cert kali

# Set kali user password for RDP login
echo "kali:kali" | chpasswd

echo "=== Base setup complete ==="
