"""Ephemeral Linux guest controls for bounded, credentialless preparation work."""

# The Google shutdown runner otherwise has an unlimited stop timeout and may
# await external services in a deliberately isolated VPC. Override only in /run
# (tmpfs), so neither this override nor project shutdown material enters images.
STARTUP = """#!/bin/bash
set -euo pipefail
trap 'poweroff' EXIT
umask 077
mkdir -p /run/systemd/system/google-shutdown-scripts.service.d
cat > /run/systemd/system/google-shutdown-scripts.service.d/preparation.conf <<'SHIFTER_SHUTDOWN'
[Service]
ExecStop=
ExecStop=/bin/true
TimeoutStopSec=10s
SHIFTER_SHUTDOWN
systemctl daemon-reload
"""
