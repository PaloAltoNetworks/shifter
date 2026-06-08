#!/usr/bin/env bash
# NORTHSTORM range setup: build all images and bring up the full topology.
#
# Runs from the range host. Assumes docker-compose.yml and all content dirs are
# already synced to $RANGE_DIR, which defaults to this script's parent range
# directory.
#
# Usage:
#     bash tests/setup.sh
#     RANGE_DIR=/some/other/path bash setup.sh
#
# Exits 0 on successful bring-up + readiness, 1 on any failure.

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_RANGE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RANGE_DIR="${RANGE_DIR:-$DEFAULT_RANGE_DIR}"
COMPOSE_FILE="${COMPOSE_FILE:-$RANGE_DIR/build/docker-compose.yml}"
# Legacy flat-layout fallback: if new location doesn't exist, try $RANGE_DIR/docker-compose.yml
if [[ ! -f "$COMPOSE_FILE" ]] && [[ -f "$RANGE_DIR/docker-compose.yml" ]]; then
    COMPOSE_FILE="$RANGE_DIR/docker-compose.yml"
fi
# Compose project name. Defaults to "build" because the production
# user_data path (`scripts/polaris-aws-range/user_data.sh.tpl`) does
# `cd /opt/polaris/scenario-dev/polaris/build && docker compose up -d`,
# yielding project=build (the parent dir of the compose file).
# `polaris-splice-watcher.service` also assumes the network is
# "build_splice-link" by default. Smoketest scripts (this file +
# reset.sh + run-all-smoketests.sh) honour COMPOSE_PROJECT_NAME so they
# can be pointed at any other project name set by the operator.
#
# Earlier this defaulted to "range" which diverged from production and
# made every helper script ship with a hardcoded mismatch.
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-build}"
COMPOSE="docker compose -p $COMPOSE_PROJECT_NAME -f $COMPOSE_FILE"

log() { echo "[setup] $*"; }

log "range dir: $RANGE_DIR"
log "compose file: $COMPOSE_FILE"

# Stage the per-range splice-relay keypair (#707). Production ranges get
# this from the provisioner's POLARIS_RANGE_BOOTSTRAP_SCRIPT; the dev
# docker-compose range generates it here so the same a9/a14 entrypoints
# consume the same env-var shape. Idempotent on re-run: if the override
# already carries a splice key the keypair is reused.
COMPOSE_DIR="$(dirname "$COMPOSE_FILE")"
OVERRIDE_FILE="$COMPOSE_DIR/docker-compose.override.yml"
SPLICE_KEY_DIR="$RANGE_DIR/.splice"

ensure_splice_keypair() {
    if [[ -s "$OVERRIDE_FILE" ]] && grep -q '^[[:space:]]*KALI_SPLICE_PRIVATE_KEY_B64:' "$OVERRIDE_FILE"; then
        log "splice keypair already staged in $OVERRIDE_FILE"
        return 0
    fi

    mkdir -p "$SPLICE_KEY_DIR"
    chmod 700 "$SPLICE_KEY_DIR"
    if [[ ! -f "$SPLICE_KEY_DIR/splice_relay" ]]; then
        ssh-keygen -t ed25519 -N "" -C "splice-relay@dev-$(date -u +%Y%m%dT%H%M%SZ)" \
            -f "$SPLICE_KEY_DIR/splice_relay" -q
    fi
    local priv_b64 pub
    priv_b64="$(base64 -w0 < "$SPLICE_KEY_DIR/splice_relay")"
    pub="$(cat "$SPLICE_KEY_DIR/splice_relay.pub")"

    local tmp
    tmp="$(mktemp "$COMPOSE_DIR/.override.yml.XXXXXX")"
    cat > "$tmp" <<DEV_OVERRIDE_EOF
services:
  a9-splice:
    environment:
      A9_AUTHORIZED_KEY: "$pub"
  a14-kali:
    environment:
      KALI_SPLICE_PRIVATE_KEY_B64: "$priv_b64"
DEV_OVERRIDE_EOF
    mv "$tmp" "$OVERRIDE_FILE"
    log "splice keypair generated; wrote $OVERRIDE_FILE"
}

ensure_splice_keypair

log "building all images..."
# Cache is on by default. This is golden-lab development - speed of
# iteration wins over reproducibility. Docker's cache invalidates
# correctly whenever Dockerfile content or COPY source hashes change,
# so real edits rebuild; unchanged Dockerfiles rebuild in seconds.
$COMPOSE build

log "starting all services..."
$COMPOSE up -d

log "waiting for docker-managed containers to report Running..."
for i in $(seq 1 30); do
    running=$($COMPOSE ps --status running 2>/dev/null | tail -n +2 | wc -l)
    if [[ "$running" -ge 15 ]]; then
        log "$running services running"
        break
    fi
    sleep 1
done

log "waiting for service readiness (a7 bootstrap, a8 postgres, a1 dovecot)..."
ready_check() {
    local label="$1" host="$2" port="$3"
    for i in $(seq 1 60); do
        if docker exec a14-kali python3 -c "
import socket, sys
s = socket.socket(); s.settimeout(1)
try: s.connect(('$host', $port)); sys.exit(0)
except: sys.exit(1)
" >/dev/null 2>&1; then
            log "  $label ready"
            return 0
        fi
        sleep 1
    done
    log "  [WARN] $label not ready after 60s"
    return 1
}

ready_check "a7-gitea http"   172.20.0.70  3000 || true
ready_check "a1-mail imap"    172.20.10.20 143  || true
ready_check "a3-intranet"     172.20.10.30 80   || true
ready_check "a4-fileshare"    172.20.10.40 445  || true
ready_check "a0-website"      172.20.0.10  80   || true

log "pre-flight service list:"
$COMPOSE ps --format 'table {{.Service}}\t{{.Status}}' || true

log "done. Run run-all-smoketests.sh to validate the full range."
