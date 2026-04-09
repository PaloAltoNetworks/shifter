#!/bin/bash
set -euo pipefail

exec > >(tee /var/log/startup-script.log) 2>&1

echo "Starting Kali GCE startup script..."

mkdir -p /home/${ssh_user}/.ssh
chmod 700 /home/${ssh_user}/.ssh
touch /home/${ssh_user}/.ssh/authorized_keys
grep -qxF "${public_key}" /home/${ssh_user}/.ssh/authorized_keys || echo "${public_key}" >> /home/${ssh_user}/.ssh/authorized_keys
chmod 600 /home/${ssh_user}/.ssh/authorized_keys
chown -R ${ssh_user}:${ssh_user} /home/${ssh_user}/.ssh

systemctl enable --now xrdp || true

echo "Kali startup script complete"
