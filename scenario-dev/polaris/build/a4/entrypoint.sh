#!/bin/bash
set -e

# Create Samba users
USERS="v.harlan:Boreas2025! m.webb:Welcome1 d.kowalski:P@ssw0rd123 svc-fileshare:F1l3Sh@r3Svc!"
for entry in $USERS; do
    user=$(echo $entry | cut -d: -f1)
    pass=$(echo $entry | cut -d: -f2)
    useradd -M -s /sbin/nologin "$user" 2>/dev/null || true
    (echo "$pass"; echo "$pass") | smbpasswd -a -s "$user" 2>/dev/null
done

# Start Samba
smbd --foreground --no-process-group
