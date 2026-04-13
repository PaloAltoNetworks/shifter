#!/bin/bash
# Base packages and user/XFCE/xrdp config for the Kali range image.
#
# This script is cloud-neutral and must run unchanged in:
#   - AWS amazon-ebs Packer builds (Kali marketplace AMI base)
#   - GCP googlecompute Packer builds (Debian 12 base; kali-linux-headless
#     metapackage gets installed in tools.sh on top)
#   - Docker buildx pod image builds (debian:12 base under supervisord)
#
# SSM agent install has been extracted to kali/aws-ssm.sh and is wired into
# only the amazon-ebs source in kali.pkr.hcl. `systemctl enable` calls go
# through the systemctl_enable helper so they no-op inside containerised
# builds where systemd is absent; supervisord starts services there instead.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../lib/systemd.sh"

export DEBIAN_FRONTEND=noninteractive

echo "=== Updating package lists ==="
apt-get update

echo "=== Ensuring kali user exists ==="
# AWS marketplace Kali ships with a `kali` user; Debian 12 (GCP VM image and
# pod image base) does not. `|| true` keeps this idempotent across all three
# build targets.
id -u kali >/dev/null 2>&1 || useradd -m -s /bin/bash kali
install -d -m 0755 /home/kali

echo "=== Installing XFCE desktop and xrdp for RDP access ==="
# Install Kali's default XFCE desktop (required for RDP sessions)
# dbus-x11 is required for xrdp session communication
apt-get install -y kali-desktop-xfce xrdp xorgxrdp dbus-x11

# Enable xrdp service (skipped inside containers; supervisord starts it)
systemctl_enable xrdp

# Create xrdp log files with correct permissions (fixes "log not initialized" error)
touch /var/log/xrdp.log /var/log/xrdp-sesman.log
chown xrdp:xrdp /var/log/xrdp.log /var/log/xrdp-sesman.log
chmod 640 /var/log/xrdp.log /var/log/xrdp-sesman.log

# Configure xrdp to use XFCE desktop session
# .xsession must unset D-Bus variables to avoid conflicts with existing sessions
cat > /home/kali/.xsession << 'EOF'
#!/bin/bash
unset DBUS_SESSION_BUS_ADDRESS
unset XDG_RUNTIME_DIR
exec startxfce4
EOF
chown kali:kali /home/kali/.xsession
chmod +x /home/kali/.xsession

# Also configure startwm.sh as backup (xrdp uses this if .xsession doesn't work)
# Backup original and create new one that starts XFCE
cp /etc/xrdp/startwm.sh /etc/xrdp/startwm.sh.bak
cat > /etc/xrdp/startwm.sh << 'EOF'
#!/bin/bash
# xrdp session startup script for Kali XFCE
unset DBUS_SESSION_BUS_ADDRESS
unset XDG_RUNTIME_DIR

# Source profile for environment
if [ -r /etc/profile ]; then
    . /etc/profile
fi

# Start XFCE session
exec startxfce4
EOF
chmod +x /etc/xrdp/startwm.sh

# Add kali user to ssl-cert group (required for xrdp)
usermod -aG ssl-cert kali

# Set kali user password for RDP login and SSH
echo "kali:kali" | chpasswd

# Override cloud-init's lock_passwd setting (20_kali.cfg sets lock_passwd: True)
# This prevents cloud-init from re-locking the account on boot
cat > /etc/cloud/cloud.cfg.d/90_shifter.cfg << 'EOF'
system_info:
  default_user:
    name: kali
    lock_passwd: false
EOF

# Enable SSH password authentication for SFTP file transfers via Guacamole
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
# Ensure it exists in config
if ! grep -q '^PasswordAuthentication' /etc/ssh/sshd_config; then
    echo 'PasswordAuthentication yes' >> /etc/ssh/sshd_config
fi

# Set home directory permissions for SFTP access
# Guacamole's SFTP (libssh2) needs read+execute on the directory
chmod 755 /home/kali

# Fix polkit for xrdp sessions (allows shutdown/restart from desktop)
mkdir -p /etc/polkit-1/localauthority/50-local.d
cat > /etc/polkit-1/localauthority/50-local.d/45-allow-colord.pkla << 'EOF'
[Allow Colord all Users]
Identity=unix-user:*
Action=org.freedesktop.color-manager.create-device;org.freedesktop.color-manager.create-profile;org.freedesktop.color-manager.delete-device;org.freedesktop.color-manager.delete-profile;org.freedesktop.color-manager.modify-device;org.freedesktop.color-manager.modify-profile
ResultAny=no
ResultInactive=no
ResultActive=yes
EOF

echo "=== Base setup complete ==="
