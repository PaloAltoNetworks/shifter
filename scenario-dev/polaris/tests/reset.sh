#!/usr/bin/env bash
# Force-recreate NORTHSTORM range services that carry sticky test state.
#
# Several asset smoketests exercise one-shot unlock sequences (A5 thermal
# runaway, A10/A11/A12 flag-register unlocks, A13 is stateless per
# connection but we reset it for safety). Without a fresh container the
# second run of the same smoketest will see "already unlocked" state and
# miss real regressions.
#
# Usage:
#     bash tests/reset.sh
#     RANGE_DIR=/other bash reset.sh
#
# Exits 0 when sticky services are recreated and responding.

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_RANGE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RANGE_DIR="${RANGE_DIR:-$DEFAULT_RANGE_DIR}"
COMPOSE_FILE="${COMPOSE_FILE:-$RANGE_DIR/build/docker-compose.yml}"
if [[ ! -f "$COMPOSE_FILE" ]] && [[ -f "$RANGE_DIR/docker-compose.yml" ]]; then
    COMPOSE_FILE="$RANGE_DIR/docker-compose.yml"
fi
# Compose project name. Defaults to "build" to match the production
# user_data path (`scripts/polaris-aws-range/user_data.sh.tpl` runs
# `docker compose up -d` from `/opt/polaris/scenario-dev/polaris/build`,
# yielding project=build). The `polaris-splice-watcher` systemd unit's
# default `SPLICE_NETWORK=build_splice-link` also assumes this. Override
# with `COMPOSE_PROJECT_NAME=...` if you bring up compose with a
# different `-p` value.
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-build}"
COMPOSE="docker compose -p $COMPOSE_PROJECT_NAME -f $COMPOSE_FILE"

STICKY=(a5-scada a10-tail a11-leg a12-arms a13-brain)
# (container, port) pairs to poll for readiness. "running" status alone is
# not sufficient - pymodbus StartTcpServer takes a few seconds after the
# python process starts, and a smoketest that connects too fast gets
# garbage or the tail end of the previous container's state.
declare -A READY_PORT=(
    [a5-scada]=502
    [a10-tail]=502
    [a11-leg]=502
    [a12-arms]=502
    [a13-brain]=9100
)

log() { echo "[reset] $*"; }

log "force-recreating sticky services: ${STICKY[*]}"
$COMPOSE up -d --force-recreate --no-deps "${STICKY[@]}"

for svc in "${STICKY[@]}"; do
    status=$(docker inspect -f '{{.State.Status}}' "$svc" 2>/dev/null || echo "missing")
    if [[ "$status" != "running" ]]; then
        log "[ERROR] $svc did not return to running"
        exit 1
    fi
done

log "polling per-service primary port on each container's own localhost..."
# Each container can always reach its own listening port on 127.0.0.1
# regardless of which docker bridge network it's attached to. This
# avoids the cross-network reachability problem (a9-splice is on
# bunker-ot only and cannot see a5-scada on the scada network).
for svc in "${STICKY[@]}"; do
    port="${READY_PORT[$svc]}"
    ready=0
    for i in $(seq 1 30); do
        if docker exec "$svc" python3 -c "
import socket, sys
s = socket.socket(); s.settimeout(1)
try: s.connect(('127.0.0.1', $port)); sys.exit(0)
except Exception: sys.exit(1)
" >/dev/null 2>&1; then
            log "  $svc:$port ready (t=${i}s)"
            ready=1
            break
        fi
        sleep 1
    done
    if (( ready == 0 )); then
        log "[ERROR] $svc:$port not ready after 30s"
        exit 1
    fi
done

log "done"
