#!/bin/bash
# Runner-side DC candidate probe for GCE pre-promoted DC images (#1343 gap 2).
#
# This runs ON THE VALIDATION RUNNER (not on the guest), probing the candidate DC
# over an IAP tunnel to its LDAP port. The trusted runner gathers the evidence
# and gates on this script's exit code, so a candidate cannot self-report a pass
# (#1343 codex security review). An LDAP rootDSE that serves the EXPECTED forest
# is authoritative proof that AD DS completed promotion and is serving — a
# pre-promoted DC must show this on a clean boot with no first-boot promotion.
# The runner runs it after the first boot and again after a reset.
#
# Inputs (env):
#   LDAP_HOST        host:port of the local end of the IAP tunnel to LDAP (389)
#   EXPECTED_DOMAIN  REQUIRED DNS domain the forest must serve (e.g.
#                    boreas.local). A DC candidate must prove a SPECIFIC forest
#                    identity — an unbound "any serving DC" pass is refused
#                    (#1343 codex Sec F2).
set -uo pipefail

log() {
  echo "shifter-validate: $*"
  return 0
}
fail() { # NOSONAR - terminates the script; an explicit return does not apply
  echo "shifter-validate: FAIL $*" >&2
  exit 1
}

LDAP_HOST="${LDAP_HOST:-localhost:389}"
EXPECTED_DOMAIN="${EXPECTED_DOMAIN:-}"

[[ -n "${EXPECTED_DOMAIN}" ]] || fail "EXPECTED_DOMAIN is required; a DC candidate must prove a specific forest identity"
command -v ldapsearch >/dev/null 2>&1 || fail "ldapsearch not available on the runner"

# Anonymous rootDSE query: no credentials, no guest login. A serving DC answers
# with the naming contexts of the forest it hosts.
ROOTDSE="$(ldapsearch -x -LLL -o ldif-wrap=no \
  -H "ldap://${LDAP_HOST}" -s base -b "" \
  defaultNamingContext rootDomainNamingContext 2>/dev/null || true)"
if [[ -z "${ROOTDSE}" ]]; then
  fail "no LDAP rootDSE response from ${LDAP_HOST} (AD DS is not serving)"
fi

DEFAULT_NC="$(echo "${ROOTDSE}" | awk -F': ' '/^defaultNamingContext:/ {print $2; exit}')"
if [[ -z "${DEFAULT_NC}" ]]; then
  fail "rootDSE has no defaultNamingContext (not a serving domain controller)"
fi
log "DC serving forest: ${DEFAULT_NC}"

# The served forest must match the expected domain (checked unconditionally;
# EXPECTED_DOMAIN is required above). Convert boreas.local -> DC=boreas,DC=local.
EXPECTED_NC="DC=${EXPECTED_DOMAIN//./,DC=}"
got="${DEFAULT_NC,,}"
want="${EXPECTED_NC,,}"
if [[ "${got}" != "${want}" ]]; then
  fail "forest mismatch: expected ${EXPECTED_NC}, got ${DEFAULT_NC}"
fi
log "forest matches expected domain ${EXPECTED_DOMAIN}"

log "PASS DC serving ${DEFAULT_NC}"
exit 0
