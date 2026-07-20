#!/bin/bash
# TechVault bake — phase 3: the VS Code over RDP seat (the Shifter access path).
# Faithful port of the retired techvault-scenario-bake.yml "seat" phase. Runs as
# root via Packer sudo. Access is Guacamole RDP into this XFCE desktop.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

apt-get install -y --no-install-recommends xfce4 xfce4-terminal xfce4-goodies dbus-x11 xorgxrdp xrdp

# VS Code Desktop from the Microsoft apt repo (real VS Code, not code-server).
wget -qO- --max-redirect=0 https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > /usr/share/keyrings/microsoft.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/code stable main" > /etc/apt/sources.list.d/vscode.list
apt-get update
apt-get install -y code

echo "xfce4-session" > /home/ubuntu/.xsession
chown ubuntu:ubuntu /home/ubuntu/.xsession
adduser xrdp ssl-cert
systemctl enable xrdp
