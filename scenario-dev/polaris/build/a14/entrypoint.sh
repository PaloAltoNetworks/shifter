#!/bin/bash
# Start sshd + xrdp for the Kali container.
set -e

# Generate SSH host keys on first boot if missing
ssh-keygen -A 2>/dev/null || true
mkdir -p /run/sshd

# Inject the operator SSH pubkey on every container start. The host EC2
# passes it via the KALI_AUTHORIZED_KEY env var set in
# docker-compose.override.yml by user_data.sh.tpl. Keeping the injection
# in the entrypoint (instead of a one-shot docker exec post-compose-up)
# means a `docker compose up -d --force-recreate a14-kali` does not wipe
# the portal terminal's key-auth path. Empty/unset value = skip.
if [[ -n "${KALI_AUTHORIZED_KEY:-}" ]]; then
    install -d -m 700 -o kali -g kali /home/kali/.ssh
    printf '%s\n' "$KALI_AUTHORIZED_KEY" > /home/kali/.ssh/authorized_keys
    chown kali:kali /home/kali/.ssh/authorized_keys
    chmod 600 /home/kali/.ssh/authorized_keys
fi

# Start sshd in the background
/usr/sbin/sshd

# xrdp needs sesman + xrdp daemons
xrdp-sesman --nodaemon &
sleep 1
exec xrdp --nodaemon
