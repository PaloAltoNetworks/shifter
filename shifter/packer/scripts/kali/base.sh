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
# dbus-x11 is required for xrdp session communication
apt-get install -y kali-desktop-xfce xrdp xorgxrdp dbus-x11

# Enable xrdp service
systemctl enable xrdp

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
# Base Kali AMI ships with account locked; chpasswd sets password but doesn't unlock
echo "kali:kali" | chpasswd
passwd -u kali

# Enable SSH password authentication for SFTP file transfers via Guacamole
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
# Ensure it exists in config
if ! grep -q '^PasswordAuthentication' /etc/ssh/sshd_config; then
    echo 'PasswordAuthentication yes' >> /etc/ssh/sshd_config
fi

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
