#!/bin/bash
# Start sshd + xrdp for the Kali container.
set -e

# Generate SSH host keys on first boot if missing
ssh-keygen -A 2>/dev/null || true
mkdir -p /run/sshd

# Start sshd in the background
/usr/sbin/sshd

# xrdp needs sesman + xrdp daemons
xrdp-sesman --nodaemon &
sleep 1
exec xrdp --nodaemon
