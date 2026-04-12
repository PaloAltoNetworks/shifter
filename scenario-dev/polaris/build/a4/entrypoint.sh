#!/bin/bash
set -e

# Groups drive share ACLs per A4 design (A4-file-share.md §2):
#   HR — HR group + Executives
#   Procurement — Procurement group + Executives
#   IT — IT group (service account has access via IT membership)
#   Executive — Executives only
for g in executives hr procurement it; do
    groupadd -f "$g"
done

# user:password:primary_groups
USERS=(
    "v.harlan:Boreas2025!:executives"
    "m.webb:Welcome1:executives"
    "d.kowalski:P@ssw0rd123:it"
    "svc-fileshare:F1l3Sh@r3Svc!:it"
)

for entry in "${USERS[@]}"; do
    IFS=':' read -r user pass groups <<< "$entry"
    useradd -M -s /sbin/nologin -G "$groups" "$user" 2>/dev/null || usermod -aG "$groups" "$user"
    (echo "$pass"; echo "$pass") | smbpasswd -a -s "$user" 2>/dev/null
done

# Share directories world-traversable so samba ACL is the only gate
find /srv/shares -type d -exec chmod 755 {} +
find /srv/shares -type f -exec chmod 644 {} +

exec smbd --foreground --no-process-group
