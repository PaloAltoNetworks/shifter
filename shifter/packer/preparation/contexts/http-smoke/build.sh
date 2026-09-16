#!/bin/bash
# Contained specimen: install exact files using only the locked base tools.
set -euo pipefail
root="${1:-/}"
[[ "${root}" == /* ]] || exit 1
context="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
install -D -m 0644 "${context}/server.py" "${root%/}/opt/shifter-http-smoke/server.py"
install -D -m 0644 "${context}/shifter-http-smoke.service" "${root%/}/etc/systemd/system/shifter-http-smoke.service"
install -d -m 0755 "${root%/}/etc/systemd/system/multi-user.target.wants"
ln -sfn ../shifter-http-smoke.service "${root%/}/etc/systemd/system/multi-user.target.wants/shifter-http-smoke.service"
