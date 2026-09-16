#!/bin/bash
# Verify the immutable build-produced source binding for one GCE candidate.
set -euo pipefail

for name in BUILD_EVIDENCE_FILE EXPECTED_REPOSITORY EXPECTED_SOURCE_REF \
  EXPECTED_SOURCE_REVISION EXPECTED_IMAGE_NAME EXPECTED_IMAGE_ID \
  EXPECTED_IMAGE_FAMILY EXPECTED_IMAGE_TYPE EXPECTED_ENVIRONMENT; do
  [[ -n "${!name:-}" ]] || { echo "::error::${name} is required" >&2; exit 1; }
done
[[ -f "${BUILD_EVIDENCE_FILE}" ]] \
  || { echo "::error::immutable build-source evidence is missing" >&2; exit 1; }
[[ "${EXPECTED_SOURCE_REVISION}" =~ ^[0-9a-f]{40}$ ]] \
  || { echo "::error::EXPECTED_SOURCE_REVISION must be a full commit SHA" >&2; exit 1; }
[[ "${EXPECTED_IMAGE_ID}" =~ ^[0-9]+$ ]] \
  || { echo "::error::EXPECTED_IMAGE_ID must be numeric" >&2; exit 1; }

expect_json() {
  local expression="$1" expected="$2" label="$3" actual
  actual="$(jq -er "${expression}" "${BUILD_EVIDENCE_FILE}")" \
    || { echo "::error::build evidence ${label} is missing or malformed" >&2; exit 1; }
  [[ "${actual}" == "${expected}" ]] \
    || { echo "::error::build evidence ${label} mismatch" >&2; exit 1; }
}

expect_json '.schema_version | tostring' "1" "schema version"
expect_json '.repository' "${EXPECTED_REPOSITORY}" "repository"
expect_json '.workflow' ".github/workflows/packer-gcp.yml" "workflow"
expect_json '.source_ref' "${EXPECTED_SOURCE_REF}" "source ref"
expect_json '.source_revision' "${EXPECTED_SOURCE_REVISION}" "source revision"
expect_json '.image_name' "${EXPECTED_IMAGE_NAME}" "image name"
expect_json '.image_id | tostring' "${EXPECTED_IMAGE_ID}" "image ID"
expect_json '.image_family' "${EXPECTED_IMAGE_FAMILY}" "image family"
expect_json '.image_type' "${EXPECTED_IMAGE_TYPE}" "image type"
expect_json '.environment' "${EXPECTED_ENVIRONMENT}" "environment"

build_run="$(jq -er '.build_run | select(type == "number") | tostring' "${BUILD_EVIDENCE_FILE}")" \
  || { echo "::error::build evidence run is missing or malformed" >&2; exit 1; }
build_attempt="$(jq -er '.build_run_attempt | select(type == "number") | tostring' "${BUILD_EVIDENCE_FILE}")" \
  || { echo "::error::build evidence run attempt is missing or malformed" >&2; exit 1; }
[[ "${build_run}" =~ ^[0-9]+$ && "${build_attempt}" =~ ^[0-9]+$ ]] \
  || { echo "::error::build evidence run identifiers must be numeric" >&2; exit 1; }

echo "Immutable build-source evidence verified for ${EXPECTED_IMAGE_NAME} (${EXPECTED_IMAGE_ID})"
