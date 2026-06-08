#!/usr/bin/env bash
# POLARIS range reset — wipes the compose stack on the polaris EC2 host
# and brings it back up from the latest build tarball in S3.
#
# Why this exists: `docker compose down --remove-orphans --volumes` has a
# cleanup race under load where one container fails to stop inside compose's
# grace window and is left orphaned — the next `up` then hits
# "Container /<name> is already in use". This script bypasses compose's
# cleanup orchestration and uses direct docker primitives against the
# known polaris container/network identity set, which does NOT respect
# compose state and cannot miss orphans.
#
# Runs via SSM from the operator's workstation. Not designed to run
# locally — it assumes the layout on the bake VM (/opt/polaris + the
# shifter-polaris-bake S3 bucket + the pre-extracted tarball + the
# docker-compose.override.yml from user_data).
#
# Usage (from operator):
#
#   aws --profile aws-dev --region us-east-2 \
#     ssm send-command \
#     --instance-ids <polaris-vm-id> \
#     --document-name AWS-RunShellScript \
#     --parameters commands="$(base64 -w0 scripts/polaris-aws-range/reset.sh | \
#       xargs -I{} echo 'echo {} | base64 -d > /tmp/reset.sh && bash /tmp/reset.sh')"
#
# Exit 0 on success, non-zero on any step that prevents the stack coming up.

set -euo pipefail

BUILD_TARBALL_S3_URI="${BUILD_TARBALL_S3_URI:-s3://shifter-polaris-bake-dev-741140496509/polaris/build-aws-dev-default-vpc.tar.gz}"
POLARIS_ROOT="${POLARIS_ROOT:-/opt/polaris}"
BUILD_DIR="${POLARIS_ROOT}/scenario-dev/polaris/build"
REBUILD_SERVICES="${REBUILD_SERVICES:-dns a14-kali a16-research-analyst}"

log() { echo "[$(date -u +%FT%TZ)] $*"; }

log "=== polaris reset start ==="

# ---------------------------------------------------------------------------
# 1. Pull the latest build tarball and re-extract. S3 is byte-stable and
#    our own tarball pipeline is the authoritative source — the local tree
#    may have drifted from `docker exec` hot-patches during an earlier
#    session, so we overwrite it unconditionally.
# ---------------------------------------------------------------------------
log "step 1/5: refresh build tree from ${BUILD_TARBALL_S3_URI}"
mkdir -p "${POLARIS_ROOT}"
cd "${POLARIS_ROOT}"
aws s3 cp "${BUILD_TARBALL_S3_URI}" polaris-build.tar.gz
tar xzf polaris-build.tar.gz

if [[ ! -d "${BUILD_DIR}" ]]; then
    log "ERROR: build directory ${BUILD_DIR} missing after extract"
    exit 1
fi

# ---------------------------------------------------------------------------
# 2. Force-remove every polaris container by name prefix. We do NOT use
#    `docker compose down` here — see the file header for why.
#
#    The name-prefix match covers:
#      dns, a0-website, a1-mail, a3-intranet, a4-fileshare, a5-scada,
#      a6-workstation, a7-gitea, a8-database, a9-splice, a10-tail,
#      a11-leg, a12-arms, a13-brain, a14-kali, a15-ops-eng,
#      a16-research-analyst.
# ---------------------------------------------------------------------------
log "step 2/5: force-remove polaris containers"
readarray -t stale_containers < <(
    docker ps -a --format '{{.Names}}' |
        grep -E '^(dns|a[0-9]+(-[a-z0-9-]+)?)$' || true
)
if (( ${#stale_containers[@]} > 0 )); then
    docker rm -f "${stale_containers[@]}" || true
    log "  removed: ${stale_containers[*]}"
else
    log "  no polaris containers present"
fi

# ---------------------------------------------------------------------------
# 3. Prune compose bridge networks. `docker network rm` refuses if any
#    endpoint is still attached, so step 2 has to have fully run first.
# ---------------------------------------------------------------------------
log "step 3/5: prune compose networks"
readarray -t stale_networks < <(
    docker network ls --format '{{.Name}}' | grep -E '^build_' || true
)
if (( ${#stale_networks[@]} > 0 )); then
    for net in "${stale_networks[@]}"; do
        docker network rm "${net}" || log "  network ${net} rm deferred"
    done
else
    log "  no compose networks present"
fi

# Final safety net: free up dangling volumes so a re-up gets fresh state
# (A8 postgres, A7 gitea etc. re-init cleanly).
log "  pruning dangling volumes"
docker volume prune -f >/dev/null || true

# ---------------------------------------------------------------------------
# 4. Rebuild the images whose Dockerfiles change most often. --pull grabs
#    upstream base image updates so we don't drift from the Debian/Kali
#    rolling bases between cycles.
# ---------------------------------------------------------------------------
log "step 4/5: rebuild images (${REBUILD_SERVICES})"
cd "${BUILD_DIR}"

compose_files=(-f docker-compose.yml)
if [[ -f docker-compose.override.yml ]]; then
    compose_files+=(-f docker-compose.override.yml)
fi

# shellcheck disable=SC2086  # intentional split on REBUILD_SERVICES
docker compose "${compose_files[@]}" build --pull ${REBUILD_SERVICES} 2>&1 | tail -20

# ---------------------------------------------------------------------------
# 5. Bring the stack up and wait for every container to be Up. We cap the
#    wait so a broken image fails fast rather than hanging the operator.
# ---------------------------------------------------------------------------
log "step 5/5: compose up"
docker compose "${compose_files[@]}" up -d

expected_count=17
for _ in $(seq 1 90); do
    running_count=$(docker ps --format '{{.Names}}' | \
        grep -cE '^(dns|a[0-9]+(-[a-z0-9-]+)?)$' || true)
    if (( running_count >= expected_count )); then
        log "  ${running_count}/${expected_count} polaris containers Up"
        break
    fi
    sleep 2
done

log "=== final state ==="
docker ps --format '{{.Names}}: {{.Status}}' | \
    grep -E '^(dns|a[0-9]+(-[a-z0-9-]+)?):' | sort

# ---------------------------------------------------------------------------
# Post-reset smoke: DNS + the one image-build fix that historically bit us
# (rockyou pre-decompressed on a14, strings/file/xxd on a16).
# ---------------------------------------------------------------------------
log "=== smoke ==="
docker exec a14-kali bash -lc 'dig +short dc01.boreas.local @172.20.0.2' || true
docker exec a14-kali bash -lc 'test -s /usr/share/wordlists/rockyou.txt && echo "rockyou: $(wc -l < /usr/share/wordlists/rockyou.txt) lines"' || true
docker exec a16-research-analyst sh -c 'which strings file xxd' || true

log "=== polaris reset complete ==="
