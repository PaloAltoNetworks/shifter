#!/bin/bash
# Polaris compose-stack fetch + verify + build for the polaris-vm image bake.
#
# Split out of host-setup.sh so the fail-closed contract can be exercised by a
# behavioral test (#1343 test-quality review): a missing stack, a checksum
# mismatch, an invalid compose config, a failed build/pull, or a missing image
# must FAIL the build (non-zero exit) when the stack is required, so a
# non-promotable polaris-vm image can never be captured. Runs as a packer
# provisioner AFTER host-setup.sh has installed Docker + the Cloud SDK.
#
# Inputs (env):
#   POLARIS_STACK_BUCKET      GCS bucket holding the compose-stack tarball
#   POLARIS_STACK_KEY         GCS object key (default polaris/stack/...)
#   POLARIS_STACK_GENERATION  optional immutable object generation to pin
#   POLARIS_STACK_SHA256      required tarball digest (when the stack is required)
#   POLARIS_REQUIRE_STACK     1 (default) = fail-closed; 0 = warn + succeed
#   HOST_MGMT_SSH_PORT        for the completion message only
set -euo pipefail

HOST_MGMT_SSH_PORT="${HOST_MGMT_SSH_PORT:-2222}"
POLARIS_STACK_BUCKET="${POLARIS_STACK_BUCKET:-}"
POLARIS_STACK_KEY="${POLARIS_STACK_KEY:-polaris/stack/polaris-stack.tar.gz}"
POLARIS_STACK_GENERATION="${POLARIS_STACK_GENERATION:-}"
POLARIS_STACK_SHA256="${POLARIS_STACK_SHA256:-}"
POLARIS_REQUIRE_STACK="${POLARIS_REQUIRE_STACK:-1}"
POLARIS_ROOT="${POLARIS_ROOT:-/opt/polaris/scenario-dev/polaris}"
COMPOSE_DIR="${COMPOSE_DIR:-${POLARIS_ROOT}/build}"

# fail_stack: emit an error and exit non-zero when the stack is required, or warn
# and succeed when it is not (POLARIS_REQUIRE_STACK=0).
fail_stack() {
  if [[ "${POLARIS_REQUIRE_STACK}" == "1" ]]; then
    echo "polaris verify-stack: ERROR $*" >&2
    exit 1
  fi
  echo "polaris verify-stack: WARNING $* (POLARIS_REQUIRE_STACK=0, leaving host range-ready without the stack)" >&2
  echo "polaris verify-stack: complete (mgmt sshd port ${HOST_MGMT_SSH_PORT}, no stack)"
  exit 0
}

if [[ -z "${POLARIS_STACK_BUCKET}" ]]; then
  fail_stack "POLARIS_STACK_BUCKET is not set; a promotable polaris-vm image requires the compose stack."
fi
if [[ "${POLARIS_REQUIRE_STACK}" == "1" && -z "${POLARIS_STACK_SHA256}" ]]; then
  echo "polaris verify-stack: ERROR POLARIS_STACK_SHA256 is required to verify the compose-stack tarball." >&2
  exit 1
fi

SOURCE_URI="gs://${POLARIS_STACK_BUCKET}/${POLARIS_STACK_KEY}"
if [[ -n "${POLARIS_STACK_GENERATION}" ]]; then
  SOURCE_URI="${SOURCE_URI}#${POLARIS_STACK_GENERATION}"
fi
echo "polaris verify-stack: fetching compose stack from ${SOURCE_URI}"
mkdir -p "${POLARIS_ROOT}"
STACK_TARBALL="$(mktemp)"
gcloud storage cp "${SOURCE_URI}" "${STACK_TARBALL}"

# Verify the tarball digest before it is unpacked or built. A mutable GCS key
# must not be able to change what gets baked without changing the declared hash.
if [[ -n "${POLARIS_STACK_SHA256}" ]]; then
  echo "${POLARIS_STACK_SHA256}  ${STACK_TARBALL}" | sha256sum -c - \
    || { rm -f "${STACK_TARBALL}"; echo "polaris verify-stack: ERROR compose-stack tarball sha256 mismatch." >&2; exit 1; }
fi

rm -rf "${COMPOSE_DIR}"
mkdir -p "${COMPOSE_DIR}"
tar xzf "${STACK_TARBALL}" -C "${COMPOSE_DIR}"
rm -f "${STACK_TARBALL}"

if [[ ! -f "${COMPOSE_DIR}/docker-compose.yml" ]]; then
  fail_stack "no docker-compose.yml at ${COMPOSE_DIR} after extracting the stack tarball."
fi

echo "polaris verify-stack: validating and building compose stack in ${COMPOSE_DIR}"
cd "${COMPOSE_DIR}"
# Fail-closed: an invalid compose file, a failed build, or a failed pull is not
# a promotable image (no `|| true`). --ignore-buildable skips images this stack
# builds locally, so a pull failure is a real registry/auth error.
docker compose config >/dev/null
docker compose build
docker compose pull --ignore-buildable

# Every image the stack references must be present after build+pull; a missing
# image means the baked host cannot start the stack on the range.
missing_images=""
while IFS= read -r img; do
  [[ -z "${img}" ]] && continue
  if ! docker image inspect "${img}" >/dev/null 2>&1; then
    missing_images="${missing_images} ${img}"
  fi
done < <(docker compose config --images)
if [[ -n "${missing_images}" ]]; then
  echo "polaris verify-stack: ERROR compose images missing after build/pull:${missing_images}" >&2
  exit 1
fi

echo "polaris verify-stack: complete (mgmt sshd port ${HOST_MGMT_SSH_PORT}, stack baked and verified)"
