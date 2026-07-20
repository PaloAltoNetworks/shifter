#!/bin/bash
# Runner-side validation evidence gathering over IAP (#1343 gap 2).
#
# Runs on the trusted validation runner. Opens an IAP tunnel to the disposable
# candidate VM (which has no external IP) and gathers evidence the RUNNER
# controls — for Linux it SSH-executes the check script and gates on its exit
# code; for a pre-promoted DC it probes AD over LDAP. A candidate cannot
# self-report a pass (#1343 codex security review). Exit 0 iff the candidate
# passed. The workflow calls this once after the first boot and again after a
# reset to prove the guest is healthy on a clean boot with no manual input.
#
# Inputs (env):
#   VM, ZONE, GCP_PROJECT_ID   the disposable validation instance
#   IMAGE_TYPE                 logical image type (routes the check)
#   SSH_PORT                   guest SSH port for Linux (22, or 2222 polaris-vm)
#   LDAP_PORT                  guest LDAP port for a DC (389)
#   EXPECTED_DOMAIN            DC forest DNS domain (dc-prebaked)
#   SSH_KEY                    private key path for the injected validator user
#   SSH_USER                   validator user provisioned via instance ssh-keys
set -uo pipefail

: "${VM:?}"
: "${ZONE:?}"
: "${GCP_PROJECT_ID:?}"
: "${IMAGE_TYPE:?}"
SSH_PORT="${SSH_PORT:-22}"
LDAP_PORT="${LDAP_PORT:-389}"
EXPECTED_DOMAIN="${EXPECTED_DOMAIN:-}"
SSH_KEY="${SSH_KEY:-}"
SSH_USER="${SSH_USER:-validator}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() {
  echo "gather-evidence: $*"
  return 0
}

if [[ "${IMAGE_TYPE}" == "dc-prebaked" ]]; then
  REMOTE_PORT="${LDAP_PORT}"
else
  REMOTE_PORT="${SSH_PORT}"
fi

# Local end of the IAP tunnel. A fixed offset keeps it deterministic per run.
LPORT=$(( REMOTE_PORT + 20000 ))

log "opening IAP tunnel to ${VM}:${REMOTE_PORT} -> localhost:${LPORT}"
gcloud compute start-iap-tunnel "${VM}" "${REMOTE_PORT}" \
  --local-host-port="localhost:${LPORT}" \
  --zone="${ZONE}" --project="${GCP_PROJECT_ID}" >/tmp/iap-tunnel.log 2>&1 &
TUNNEL_PID=$!
# Invoked indirectly via `trap ... EXIT`.
# shellcheck disable=SC2329
cleanup() {
  kill "${TUNNEL_PID}" 2>/dev/null || true
  return 0
}
trap cleanup EXIT

# Wait for the tunnel's local port to accept connections (VM boot + tunnel).
tunnel_up=0
for _ in $(seq 1 60); do
  if timeout 3 bash -c "exec 3<>/dev/tcp/localhost/${LPORT}" 2>/dev/null; then
    tunnel_up=1
    break
  fi
  sleep 10
done
if [[ "${tunnel_up}" -ne 1 ]]; then
  echo "::error::IAP tunnel to ${VM}:${REMOTE_PORT} never became reachable" >&2
  exit 1
fi
log "tunnel reachable"

if [[ "${IMAGE_TYPE}" == "dc-prebaked" ]]; then
  # Runner-side AD probe; retry while AD DS finishes coming up after boot.
  command -v ldapsearch >/dev/null 2>&1 || { echo "::error::ldapsearch not installed on the runner" >&2; exit 1; }
  # A dc-prebaked validation MUST prove a specific forest identity; refuse when
  # the expected domain was not resolved (#1343 codex Sec F2).
  if [[ -z "${EXPECTED_DOMAIN}" ]]; then
    echo "::error::no expected domain resolved for the DC profile; refusing to validate an unbound forest" >&2
    exit 1
  fi
  # rc stays non-zero unless a probe actually SUCCEEDS. Do NOT read $? after the
  # if-compound: bash returns 0 when no branch runs, which would turn an
  # all-failed retry loop into a false pass (#1343 codex Core F1).
  rc=1
  for _ in $(seq 1 30); do
    if LDAP_HOST="localhost:${LPORT}" EXPECTED_DOMAIN="${EXPECTED_DOMAIN}" \
        bash "${SCRIPT_DIR}/dc-probe.sh"; then
      rc=0
      break
    fi
    sleep 15
  done
  exit "${rc}"
fi

# Linux: SSH-execute the check script; the runner gates on its exit code. Retry
# ONLY on ssh connection errors (255) while the guest finishes booting; a script
# that ran and failed is a real, immediate failure.
[[ -n "${SSH_KEY}" ]] || { echo "::error::SSH_KEY not provided for Linux validation" >&2; exit 1; }
rc=255
for _ in $(seq 1 40); do
  ssh -i "${SSH_KEY}" -p "${LPORT}" \
    -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o ConnectTimeout=15 -o BatchMode=yes \
    "${SSH_USER}@localhost" \
    "sudo VALIDATE_IMAGE_TYPE='${IMAGE_TYPE}' MGMT_SSH_PORT='${SSH_PORT}' bash -s" \
    < "${SCRIPT_DIR}/linux.sh"
  rc=$?
  [[ "${rc}" -ne 255 ]] && break
  sleep 10
done
exit "${rc}"
