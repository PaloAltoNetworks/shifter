#!/bin/bash
# Verify that a GCE promotion candidate is bound to a successful protected
# validation run and that run's exact private evidence objects (ADR-004-R23).
set -euo pipefail

readonly SHA256_VALUE_PROGRAM='{print $1}'

for name in SRC_IMAGE SRC_IMAGE_ID SRC_PROJECT IMAGE_FAMILY IMAGE_TYPE VALIDATED_RUN \
  VALIDATED_RUN_ATTEMPT VALIDATED_VERDICT_ID VALIDATED_EVIDENCE_SHA \
  VALIDATED_REVISION EXPECTED_REPOSITORY EVIDENCE_FILE GUEST_SBOM_FILE \
  VERDICT_FILE RUN_FILE ARTIFACT_FILE; do
  [[ -n "${!name:-}" ]] || { echo "::error::${name} is required" >&2; exit 1; }
done
[[ -f "${EVIDENCE_FILE}" ]] || { echo "::error::private validation evidence is missing" >&2; exit 1; }
[[ -f "${GUEST_SBOM_FILE}" ]] || { echo "::error::private guest SBOM is missing" >&2; exit 1; }
[[ -f "${VERDICT_FILE}" ]] || { echo "::error::redacted validation verdict is missing" >&2; exit 1; }
[[ -f "${RUN_FILE}" ]] || { echo "::error::validation workflow run metadata is missing" >&2; exit 1; }
[[ -f "${ARTIFACT_FILE}" ]] || { echo "::error::validation verdict artifact metadata is missing" >&2; exit 1; }

for value_name in SRC_IMAGE_ID VALIDATED_RUN VALIDATED_RUN_ATTEMPT VALIDATED_VERDICT_ID; do
  [[ "${!value_name}" =~ ^[0-9]+$ ]] \
    || { echo "::error::${value_name} must be a numeric identifier" >&2; exit 1; }
done
[[ "${VALIDATED_REVISION}" =~ ^[0-9a-f]{40}$ ]] \
  || { echo "::error::VALIDATED_REVISION must be a full commit SHA" >&2; exit 1; }
[[ "${VALIDATED_EVIDENCE_SHA}" =~ ^[0-9a-f]{63}$ ]] \
  || { echo "::error::VALIDATED_EVIDENCE_SHA must be a 63-character digest prefix" >&2; exit 1; }
actual_evidence_sha="$(sha256sum "${EVIDENCE_FILE}" | awk "${SHA256_VALUE_PROGRAM}")"
[[ "${actual_evidence_sha:0:63}" == "${VALIDATED_EVIDENCE_SHA}" ]] \
  || { echo "::error::private validation evidence digest mismatch" >&2; exit 1; }

expect_json() {
  local file="$1" expression="$2" expected="$3" label="$4" actual
  actual="$(jq -er "${expression}" "${file}")" \
    || { echo "::error::${label} is missing or malformed" >&2; exit 1; }
  [[ "${actual}" == "${expected}" ]] \
    || { echo "::error::${label} mismatch" >&2; exit 1; }
}

expect_json "${RUN_FILE}" '.id | tostring' "${VALIDATED_RUN}" "validation run id"
expect_json "${RUN_FILE}" '.run_attempt | tostring' "${VALIDATED_RUN_ATTEMPT}" "validation run attempt"
expect_json "${RUN_FILE}" '.name' "Packer GCE Image Validate" "validation workflow name"
expect_json "${RUN_FILE}" '.path' ".github/workflows/packer-gcp-validate.yml" "validation workflow path"
expect_json "${RUN_FILE}" '.event' "workflow_dispatch" "validation event"
expect_json "${RUN_FILE}" '.conclusion' "success" "validation conclusion"
expect_json "${RUN_FILE}" '.head_sha' "${VALIDATED_REVISION}" "validation revision"
expect_json "${RUN_FILE}" '.repository.full_name' "${EXPECTED_REPOSITORY}" "validation repository"
branch="$(jq -er '.head_branch' "${RUN_FILE}")"
case "${branch}" in
  dev|main) ;;
  *) echo "::error::validation run did not execute from a protected branch" >&2; exit 1 ;;
esac

expect_json "${ARTIFACT_FILE}" '.id | tostring' "${VALIDATED_VERDICT_ID}" "validation verdict artifact id"
expect_json "${ARTIFACT_FILE}" '.name' "${IMAGE_TYPE}-gce-validation-verdict" "validation verdict artifact name"
expect_json "${ARTIFACT_FILE}" '.expired | tostring' "false" "validation verdict artifact expiry"
expect_json "${ARTIFACT_FILE}" '.workflow_run.id | tostring' "${VALIDATED_RUN}" "validation verdict artifact run"

expect_json "${VERDICT_FILE}" '.schema_version | tostring' "2" "verdict schema version"
expect_json "${VERDICT_FILE}" '.source_sha' "${VALIDATED_REVISION}" "verdict source revision"
expect_json "${VERDICT_FILE}" '.image_type' "${IMAGE_TYPE}" "verdict image type"
expect_json "${VERDICT_FILE}" '.result' "passed" "verdict result"
expect_json "${VERDICT_FILE}" '.evidence_sha256' "${actual_evidence_sha}" "verdict evidence digest"
evidence_prefix="packer-validation/${SRC_IMAGE_ID}/${VALIDATED_RUN}/${VALIDATED_RUN_ATTEMPT}"
expected_locator="$(printf '%s' "${evidence_prefix}" | sha256sum | awk "${SHA256_VALUE_PROGRAM}")"
expect_json "${VERDICT_FILE}" '.evidence_locator' "${expected_locator}" "verdict evidence locator"
candidate_binding_sha="$(
  jq -cnS \
    --arg candidate_project "${SRC_PROJECT}" \
    --arg candidate_image "${SRC_IMAGE}" \
    --arg candidate_image_id "${SRC_IMAGE_ID}" \
    --arg image_family "${IMAGE_FAMILY}" \
    --arg image_type "${IMAGE_TYPE}" \
    --arg source_revision "${VALIDATED_REVISION}" \
    --arg evidence_sha256 "${actual_evidence_sha}" \
    '{candidate_project: $candidate_project, candidate_image: $candidate_image, candidate_image_id: $candidate_image_id, image_family: $image_family, image_type: $image_type, source_revision: $source_revision, evidence_sha256: $evidence_sha256}' \
    | sha256sum | awk "${SHA256_VALUE_PROGRAM}"
)"
expect_json "${VERDICT_FILE}" '.candidate_binding_sha256' "${candidate_binding_sha}" "verdict candidate binding"

expect_json "${EVIDENCE_FILE}" '.schema_version | tostring' "3" "evidence schema version"
expect_json "${EVIDENCE_FILE}" '.repository' "${EXPECTED_REPOSITORY}" "evidence repository"
expect_json "${EVIDENCE_FILE}" '.workflow' ".github/workflows/packer-gcp-validate.yml" "evidence workflow"
expect_json "${EVIDENCE_FILE}" '.source_ref' "refs/heads/${branch}" "evidence source ref"
expect_json "${EVIDENCE_FILE}" '.candidate_image' "${SRC_IMAGE}" "candidate image"
expect_json "${EVIDENCE_FILE}" '.candidate_image_id | tostring' "${SRC_IMAGE_ID}" "candidate image id"
expect_json "${EVIDENCE_FILE}" '.project' "${SRC_PROJECT}" "candidate project"
expect_json "${EVIDENCE_FILE}" '.environment' "dev" "promotion source environment"
expect_json "${EVIDENCE_FILE}" '.image_family' "${IMAGE_FAMILY}" "candidate family"
expect_json "${EVIDENCE_FILE}" '.image_type' "${IMAGE_TYPE}" "candidate image type"
expect_json "${EVIDENCE_FILE}" '.source_revision' "${VALIDATED_REVISION}" "evidence revision"
expect_json "${EVIDENCE_FILE}" '.validation_run | tostring' "${VALIDATED_RUN}" "evidence validation run"
expect_json "${EVIDENCE_FILE}" '.validation_run_attempt | tostring' "${VALIDATED_RUN_ATTEMPT}" "evidence run attempt"
expect_json "${EVIDENCE_FILE}" '(.phases == ["first_boot_health", "reboot_health"]) | tostring' "true" "evidence phases"
expect_json "${EVIDENCE_FILE}" '.guest_sbom_file' "guest-sbom.spdx.json" "guest SBOM file"
expect_json "${EVIDENCE_FILE}" '.guest_sbom_format' "spdx-json" "guest SBOM format"
expect_json "${EVIDENCE_FILE}" '.guest_sbom_collection' "external-read-only-disk" "guest SBOM collection boundary"
expect_json "${EVIDENCE_FILE}" '.guest_sbom_source_image_id | tostring' "${SRC_IMAGE_ID}" "guest SBOM source image ID"
guest_sbom_tool="$(jq -er '.guest_sbom_tool' "${EVIDENCE_FILE}")" \
  || { echo "::error::guest SBOM tool is missing" >&2; exit 1; }
[[ "${guest_sbom_tool}" =~ ^syft/[0-9]+\.[0-9]+\.[0-9]+$ ]] \
  || { echo "::error::guest SBOM tool is malformed" >&2; exit 1; }
guest_sbom_sha256="$(jq -er '.guest_sbom_sha256' "${EVIDENCE_FILE}")" \
  || { echo "::error::guest SBOM digest is missing" >&2; exit 1; }
[[ "${guest_sbom_sha256}" =~ ^[0-9a-f]{64}$ ]] \
  || { echo "::error::guest SBOM digest is malformed" >&2; exit 1; }
actual_guest_sbom_sha256="$(sha256sum "${GUEST_SBOM_FILE}" | awk "${SHA256_VALUE_PROGRAM}")"
[[ "${actual_guest_sbom_sha256}" == "${guest_sbom_sha256}" ]] \
  || { echo "::error::guest SBOM digest mismatch" >&2; exit 1; }
jq -e '.spdxVersion | startswith("SPDX-")' "${GUEST_SBOM_FILE}" >/dev/null \
  || { echo "::error::guest SBOM is not valid SPDX JSON" >&2; exit 1; }
jq -e '.packages | length > 0' "${GUEST_SBOM_FILE}" >/dev/null \
  || { echo "::error::guest SBOM contains no packages" >&2; exit 1; }
jq -e '.guest_sbom_scanner_image | type == "string" and length > 0' "${EVIDENCE_FILE}" >/dev/null \
  || { echo "::error::guest SBOM scanner image is missing" >&2; exit 1; }
scanner_image_id="$(jq -er '.guest_sbom_scanner_image_id | select(type == "string")' "${EVIDENCE_FILE}")" \
  || { echo "::error::guest SBOM scanner image ID is missing" >&2; exit 1; }
[[ "${scanner_image_id}" =~ ^[0-9]+$ ]] \
  || { echo "::error::guest SBOM scanner image ID must be numeric" >&2; exit 1; }
expect_json "${EVIDENCE_FILE}" '.result' "passed" "validation result"
validated_at="$(jq -er '.validated_at_utc' "${EVIDENCE_FILE}")" \
  || { echo "::error::validation timestamp is missing or malformed" >&2; exit 1; }
[[ "${validated_at}" =~ ^[0-9]{8}T[0-9]{6}$ ]] \
  || { echo "::error::validation timestamp is malformed" >&2; exit 1; }

echo "Promotion evidence verified for ${SRC_IMAGE} (${SRC_IMAGE_ID}, run ${VALIDATED_RUN}/${VALIDATED_RUN_ATTEMPT}, verdict ${VALIDATED_VERDICT_ID}, private evidence ${VALIDATED_EVIDENCE_SHA:0:16}...)"
