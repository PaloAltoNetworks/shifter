#!/bin/bash
# Candidate-boot validation checks for GCE Linux range-host images (#1343 gap 2).
#
# This script is EXECUTED BY THE VALIDATION RUNNER over an IAP SSH tunnel, not by
# the guest's own startup — the trusted runner gathers the evidence and gates on
# this script's EXIT CODE, so a candidate cannot self-report a pass (#1343 codex
# security review). It exits non-zero on the first failed check and 0 only when
# every check for the profile passes. The runner runs it once per boot (first
# boot and again after a reset) to prove the guest comes back healthy with no
# manual input.
#
# Inputs (env, set by the runner on the ssh command line):
#   VALIDATE_IMAGE_TYPE  logical image type (e.g. polaris-vm, ubuntu)
#   MGMT_SSH_PORT        polaris-vm host management sshd port (default 2222)
set -uo pipefail

log() {
  echo "shifter-validate: $*"
  return 0
}
fail() { # NOSONAR - terminates the script; an explicit return does not apply
  echo "shifter-validate: FAIL $*" >&2
  exit 1
}

IMAGE_TYPE="${VALIDATE_IMAGE_TYPE:-}"
MGMT_SSH_PORT="${MGMT_SSH_PORT:-2222}"
log "validating image_type=${IMAGE_TYPE:-unknown}"

# --- Google guest environment (all Linux guests) ------------------------------
# The guest agent provides metadata SSH keys + networking; a captured image that
# lost it is unbootable-in-practice on GCE.
if ! systemctl is-active --quiet google-guest-agent; then
  fail "google-guest-agent is not active"
fi
log "google-guest-agent active"

# --- polaris-vm profile: Docker host + compose stack --------------------------
if [[ "${IMAGE_TYPE}" == "polaris-vm" ]]; then
  COMPOSE_DIR="/opt/polaris/scenario-dev/polaris/build"

  # The participant Kali container binds host :22, so the baked host sshd must
  # listen on the management port (host-setup.sh drop-in). Prove the drop-in
  # took effect on a fresh boot.
  if ! ss -tlnH "sport = :${MGMT_SSH_PORT}" | grep -q ":${MGMT_SSH_PORT}"; then
    fail "host sshd is not listening on management port ${MGMT_SSH_PORT}"
  fi
  log "host sshd listening on management port ${MGMT_SSH_PORT}"

  if ! systemctl is-active --quiet docker; then
    fail "docker daemon is not active"
  fi
  if ! docker compose version >/dev/null 2>&1; then
    fail "docker compose plugin is not available"
  fi
  log "docker daemon + compose plugin present"

  if [[ ! -f "${COMPOSE_DIR}/docker-compose.yml" ]]; then
    fail "no baked compose stack at ${COMPOSE_DIR} (image is not a promotable polaris-vm)"
  fi
  cd "${COMPOSE_DIR}" || fail "cannot enter ${COMPOSE_DIR}"

  if ! docker compose config >/dev/null 2>&1; then
    fail "baked docker compose config is invalid"
  fi
  log "compose config valid"

  # Every referenced image must already be present (baked); the range host has
  # no external IP to pull at runtime.
  missing=""
  while IFS= read -r img; do
    [[ -z "${img}" ]] && continue
    docker image inspect "${img}" >/dev/null 2>&1 || missing="${missing} ${img}"
  done < <(docker compose config --images)
  if [[ -n "${missing}" ]]; then
    fail "baked compose images missing:${missing}"
  fi
  log "all baked compose images present"

  # Bring the stack up and require EVERY declared service to have a running
  # container. Checking the full declared-service set (not just `docker compose
  # ps`, which hides absent/exited containers) prevents a crashed or missing
  # required container from silently passing (#1343 codex Core F1). We gate on
  # "running", not healthcheck status: a container whose healthcheck needs a
  # per-range runtime credential is a runtime concern, but it must still start.
  if ! docker compose up -d; then
    fail "docker compose up failed"
  fi
  mapfile -t services < <(docker compose config --services)
  [[ "${#services[@]}" -gt 0 ]] || fail "compose declares no services"
  deadline=$(( SECONDS + 300 ))
  while :; do
    notready=""
    for svc in "${services[@]}"; do
      state="$(docker compose ps -a --format '{{.Service}} {{.State}}' \
        | awk -v s="${svc}" '$1==s {print $2; f=1} END{if(!f) print "absent"}')"
      [[ "${state}" == "running" ]] || notready="${notready} ${svc}(${state})"
    done
    [[ -z "${notready}" ]] && break
    if (( SECONDS >= deadline )); then
      fail "compose services not running within timeout:${notready}"
    fi
    log "waiting for services to reach running:${notready}"
    sleep 15
  done
  log "compose stack up: all ${#services[@]} declared services running"
fi

log "PASS image_type=${IMAGE_TYPE:-unknown}"
exit 0
