#!/bin/bash
# Shifter Kali scenario pod entrypoint.
#
# Regenerates SSH host keys on every fresh pod start (the Packer
# common/cleanup.sh step removes them from the VM image, and containers
# start without them because we never run that step; we still want per-pod
# unique host keys), then hands control to supervisord which runs sshd,
# xrdp-sesman, and xrdp in the foreground with logs wired to the pod's
# stdout/stderr.
set -euo pipefail

echo "[entrypoint] regenerating SSH host keys"
install -d -m 0755 /etc/ssh
ssh-keygen -A

echo "[entrypoint] ensuring /run/sshd exists (required by some sshd builds)"
install -d -m 0755 /run/sshd

echo "[entrypoint] exec supervisord"
exec /usr/bin/supervisord -n -c /etc/supervisor/conf.d/shifter.conf
