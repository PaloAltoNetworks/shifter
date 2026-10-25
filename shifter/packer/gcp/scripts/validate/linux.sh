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
#   VALIDATE_IMAGE_TYPE  logical base image type (e.g. ubuntu)
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
case "$IMAGE_TYPE" in
  ubuntu|brokenbk|kali) ;;
  *) fail "unsupported image type: ${IMAGE_TYPE:-missing}" ;;
esac
log "validating image_type=${IMAGE_TYPE}"

# --- Google guest environment (all Linux guests) ------------------------------
# The guest agent provides metadata SSH keys + networking; a captured image that
# lost it is unbootable-in-practice on GCE.
if ! systemctl is-active --quiet google-guest-agent; then
  fail "google-guest-agent is not active"
fi
log "google-guest-agent active"

log "PASS image_type=${IMAGE_TYPE:-unknown}"
exit 0
