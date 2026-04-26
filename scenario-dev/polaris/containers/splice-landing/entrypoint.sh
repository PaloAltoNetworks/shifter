#!/bin/sh
set -eu

# Scenario may drop an authorized_keys for the splice user once the gate fires.
if [ -f /generated/authorized_keys ]; then
    mkdir -p /home/splice/.ssh
    cp /generated/authorized_keys /home/splice/.ssh/authorized_keys
    chown -R splice:splice /home/splice/.ssh
    chmod 600 /home/splice/.ssh/authorized_keys
fi

# Pre-scanned nmap output for operator fallback.
mkdir -p /root
if [ -f /generated/scan_results.txt ]; then
    cp /generated/scan_results.txt /root/scan_results.txt
fi

exec /usr/sbin/sshd -D -e
