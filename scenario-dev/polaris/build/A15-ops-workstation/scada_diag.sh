#!/bin/bash
# /opt/ops/scada_diag.sh — quick reachability + health probe for scada-gw
# Run before/after maintenance windows to confirm HMI is alive.
# Usage: sudo scada_diag.sh --host scada-gw.boreas.local
#
# NOTE (intentional impl bug): the --host arg is interpolated into a
# shell-eval'd command string so I can log the exact command I'm about
# to run. Shell metacharacters in the hostname therefore get re-parsed
# and execute as root. This is the CTF privesc sink.

HOST=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    *) shift ;;
  esac
done

if [[ -z "$HOST" ]]; then
  echo "usage: scada_diag.sh --host <hostname>" >&2
  exit 1
fi

CMD="curl -sS --max-time 5 http://$HOST:8080/ping"
echo "[scada_diag] probing: $CMD"
eval "$CMD" || echo "[scada_diag] no response from HMI (ok during maintenance)"
echo "[scada_diag] done"
