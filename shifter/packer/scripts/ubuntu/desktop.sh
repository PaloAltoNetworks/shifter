#!/bin/bash
# XFCE desktop and xrdp for Ubuntu RDP access via Guacamole
# Follows patterns established in kali/base.sh
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

echo "=== Installing XFCE desktop and xrdp for RDP access ==="
# Install lightweight XFCE desktop (ubuntu-desktop is too heavy)
# dbus-x11 is required for xrdp session communication
apt-get install -y xfce4 xfce4-goodies xrdp xorgxrdp dbus-x11

# Enable xrdp service
systemctl enable xrdp

# Create xrdp log files with correct permissions (fixes "log not initialized" error)
touch /var/log/xrdp.log /var/log/xrdp-sesman.log
chown xrdp:xrdp /var/log/xrdp.log /var/log/xrdp-sesman.log
chmod 640 /var/log/xrdp.log /var/log/xrdp-sesman.log

# Configure xrdp to use XFCE desktop session
# .xsession must unset D-Bus variables to avoid conflicts with existing sessions
cat > /home/ubuntu/.xsession << 'EOF'
#!/bin/bash
unset DBUS_SESSION_BUS_ADDRESS
unset XDG_RUNTIME_DIR
exec startxfce4
EOF
chown ubuntu:ubuntu /home/ubuntu/.xsession
chmod +x /home/ubuntu/.xsession

# Also configure startwm.sh as backup (xrdp uses this if .xsession doesn't work)
# Backup original and create new one that starts XFCE
cp /etc/xrdp/startwm.sh /etc/xrdp/startwm.sh.bak
cat > /etc/xrdp/startwm.sh << 'EOF'
#!/bin/bash
# xrdp session startup script for Ubuntu XFCE
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

# Add ubuntu user to ssl-cert group (required for xrdp)
usermod -aG ssl-cert ubuntu

# Set ubuntu user password for RDP login
# nosec B105 - Ephemeral isolated range, not a production credential
echo "ubuntu:ubuntu" | chpasswd

# Enable SSH password authentication for SFTP file transfers via Guacamole
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
# Ensure it exists in config
if ! grep -q '^PasswordAuthentication' /etc/ssh/sshd_config; then
    echo 'PasswordAuthentication yes' >> /etc/ssh/sshd_config
fi

# Set home directory permissions for SFTP access
# Guacamole's SFTP (libssh2) needs read+execute on the directory
chmod 755 /home/ubuntu

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

echo "=== Desktop setup complete ==="
