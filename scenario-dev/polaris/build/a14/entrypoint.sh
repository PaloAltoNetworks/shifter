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

# Stage the participant-discoverable splice-relay private key (#707). The
# range bootstrap generates a per-range Ed25519 keypair and passes the
# private half here as base64 in KALI_SPLICE_PRIVATE_KEY_B64 (base64 keeps
# the value on a single YAML line so docker-compose.override.yml stays
# trivial to render from a bash heredoc; raw multi-line interpolation
# would break the override). The matching public half lands in A9's
# /root/.ssh/authorized_keys. ssh_config aliases splice-relay ->
# IdentityFile so the documented walkthrough verb
# (`ssh root@splice-relay`) keeps working without exposing key material
# on argv. Empty/unset value = skip (A9 password auth still off, bunker
# chain just isn't reachable until the range bootstrap re-runs).
if [[ -n "${KALI_SPLICE_PRIVATE_KEY_B64:-}" ]]; then
    install -d -m 700 -o kali -g kali /home/kali/.ssh
    printf '%s' "$KALI_SPLICE_PRIVATE_KEY_B64" | base64 -d > /home/kali/.ssh/splice_relay
    chown kali:kali /home/kali/.ssh/splice_relay
    chmod 600 /home/kali/.ssh/splice_relay
    install -d -m 700 /root/.ssh
    cp /home/kali/.ssh/splice_relay /root/.ssh/splice_relay
    chmod 600 /root/.ssh/splice_relay

    config_file=/home/kali/.ssh/config
    if ! [[ -f "$config_file" ]] || ! grep -q '^Host splice-relay' "$config_file"; then
        cat >> "$config_file" <<'CFG_EOF'

Host splice-relay
    User root
    IdentityFile ~/.ssh/splice_relay
    IdentitiesOnly yes
    StrictHostKeyChecking accept-new
    UserKnownHostsFile ~/.ssh/known_hosts
CFG_EOF
        chown kali:kali "$config_file"
        chmod 600 "$config_file"
    fi

    root_config_file=/root/.ssh/config
    if ! [[ -f "$root_config_file" ]] || ! grep -q '^Host splice-relay' "$root_config_file"; then
        cat >> "$root_config_file" <<'CFG_EOF'

Host splice-relay
    User root
    IdentityFile ~/.ssh/splice_relay
    IdentitiesOnly yes
    StrictHostKeyChecking accept-new
    UserKnownHostsFile ~/.ssh/known_hosts
CFG_EOF
        chmod 600 "$root_config_file"
    fi
fi

# Start sshd in the background
/usr/sbin/sshd

# xrdp needs sesman + xrdp daemons
xrdp-sesman --nodaemon &
sleep 1
exec xrdp --nodaemon
