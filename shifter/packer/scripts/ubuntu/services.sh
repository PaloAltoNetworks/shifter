#!/bin/bash
# Install and configure services for Ubuntu victim AMI
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

# Refresh package lists after base.sh upgrade
apt-get update

echo "=== Installing Apache with PHP ==="
apt-get install -y apache2 libapache2-mod-php php php-mysqli

echo "=== Installing MySQL 8.0 ==="
apt-get install -y mysql-server

echo "=== Installing Docker ==="
apt-get install -y docker.io
usermod -aG docker ubuntu

echo "=== Installing OpenSSH Server ==="
# Usually pre-installed, but ensure it's there
apt-get install -y openssh-server

# Issue #762: no shared static password baked into the AMI. The
# per-range Terraform user_data sets a per-instance password on first
# boot.

# Enable SSH password authentication for SFTP file transfers via Guacamole
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
# Ensure it exists in config
if ! grep -q '^PasswordAuthentication' /etc/ssh/sshd_config; then
    echo 'PasswordAuthentication yes' >> /etc/ssh/sshd_config
fi

echo "=== Installing vsftpd (FTP server) ==="
apt-get install -y vsftpd

echo "=== Installing Samba (not enabled) ==="
apt-get install -y samba

echo "=== Enabling services ==="
systemctl enable apache2
systemctl enable mysql
systemctl enable docker
systemctl enable ssh
systemctl enable vsftpd
# Samba intentionally NOT enabled per requirements

echo "=== Services setup complete ==="
