#!/bin/bash
# Install and configure services for the Ubuntu range image.
#
# Cloud-neutral: every `systemctl enable` goes through systemctl_enable so
# the call no-ops inside containerised builds where systemd is absent and
# supervisord launches services instead.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../lib/systemd.sh"

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

# Set ubuntu user password for SSH/SFTP
echo "ubuntu:ubuntu" | chpasswd

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
systemctl_enable apache2
systemctl_enable mysql
systemctl_enable docker
systemctl_enable ssh
systemctl_enable vsftpd
# Samba intentionally NOT enabled per requirements

echo "=== Services setup complete ==="
