#!/bin/sh
# A9 splice-landing entrypoint: install the participant-discoverable
# authorized_keys then exec sshd.
#
# The public key is delivered via the A9_AUTHORIZED_KEY env var by the
# range bootstrap (provisioner for EC2 ranges, tests/setup.sh for the
# docker-compose dev range) and consumed here on every container start.
# Per #707, password auth is off on A9; this key path is the only way in.
# An empty/unset env var = no key installed and sshd starts refusing
# auth (useful for inspection / debugging without changing the image).
set -eu

mkdir -p /root/.ssh
chmod 700 /root/.ssh

if [ -n "${A9_AUTHORIZED_KEY:-}" ]; then
    printf '%s\n' "$A9_AUTHORIZED_KEY" > /root/.ssh/authorized_keys
    chmod 600 /root/.ssh/authorized_keys
fi

exec /usr/sbin/sshd -D
