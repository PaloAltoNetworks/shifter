#!/usr/bin/env bash
# Post-deploy live range smoke for GCP (issue #1638).
#
# Runs ``python manage.py run_post_deploy_smoke`` in a short-lived Job derived
# from the deployed portal pod template. This keeps the live image, identity,
# network placement and runtime configuration without requiring a streaming
# ``kubectl exec`` connection through GKE Connect Gateway.
set -euo pipefail

VARIANT="linux"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --variant)
      VARIANT="${2:?--variant requires a value}"
      shift 2
      ;;
    -h | --help)
      echo "Usage: $0 [--variant linux|windows]"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "${SMOKE_TEST_USER_EMAIL:-}" ]]; then
  echo "::error::SMOKE_TEST_USER_EMAIL is required" >&2
  exit 1
fi

KUBECTL_REQUEST_TIMEOUT="${KUBECTL_REQUEST_TIMEOUT:-3600s}"
SMOKE_TIMEOUT_SECONDS="${SMOKE_TIMEOUT_SECONDS:-3600}"
if [[ ! "${SMOKE_TIMEOUT_SECONDS}" =~ ^[0-9]+$ ]] ||
  ((SMOKE_TIMEOUT_SECONDS < 60 || SMOKE_TIMEOUT_SECONDS > 7200)); then
  echo "::error::SMOKE_TIMEOUT_SECONDS must be between 60 and 7200" >&2
  exit 2
fi

run_identity="${GITHUB_RUN_ID:-manual}-${GITHUB_RUN_ATTEMPT:-1}"
job_name="post-deploy-smoke-${run_identity}"
secret_name="${job_name}-identity"
if ((${#secret_name} > 63)); then
  echo "::error::Smoke resource identity exceeds the Kubernetes name limit" >&2
  exit 2
fi

namespace="shifter-platform"
temporary_directory="$(mktemp -d)"

# shellcheck disable=SC2329  # invoked by the EXIT trap below
cleanup() {
  local result=$?
  kubectl -n "${namespace}" delete "job/${job_name}" "secret/${secret_name}" \
    --ignore-not-found --wait=false --request-timeout="${KUBECTL_REQUEST_TIMEOUT}" >/dev/null 2>&1 || true
  python3 - "${temporary_directory}" <<'PY'
from pathlib import Path
import shutil
import sys

shutil.rmtree(Path(sys.argv[1]), ignore_errors=True)
PY
  trap - EXIT
  exit "${result}"
}
trap cleanup EXIT

identity_file="${temporary_directory}/smoke-identity"
printf '%s' "${SMOKE_TEST_USER_EMAIL}" > "${identity_file}"
chmod 600 "${identity_file}"
kubectl -n "${namespace}" create secret generic "${secret_name}" \
  --from-file="SMOKE_TEST_USER_EMAIL=${identity_file}" --dry-run=client -o json |
  kubectl apply -f - --request-timeout="${KUBECTL_REQUEST_TIMEOUT}" >/dev/null

deployment_file="${temporary_directory}/portal-deployment.json"
job_file="${temporary_directory}/smoke-job.json"
kubectl -n "${namespace}" get deployment/portal-web -o json \
  --request-timeout="${KUBECTL_REQUEST_TIMEOUT}" > "${deployment_file}"
python3 scripts/gcp/render_smoke_job.py \
  --deployment "${deployment_file}" \
  --output "${job_file}" \
  --name "${job_name}" \
  --secret-name "${secret_name}" \
  --variant "${VARIANT}" \
  --active-deadline-seconds "${SMOKE_TIMEOUT_SECONDS}"
kubectl apply -f "${job_file}" --request-timeout="${KUBECTL_REQUEST_TIMEOUT}" >/dev/null

deadline=$((SECONDS + SMOKE_TIMEOUT_SECONDS + 60))
while ((SECONDS < deadline)); do
  job_status="$(kubectl -n "${namespace}" get job "${job_name}" -o json \
    --request-timeout="${KUBECTL_REQUEST_TIMEOUT}")"
  if [[ "$(jq -r '.status.succeeded // 0' <<<"${job_status}")" -ge 1 ]]; then
    kubectl -n "${namespace}" logs "job/${job_name}" --request-timeout="${KUBECTL_REQUEST_TIMEOUT}"
    exit 0
  fi
  if [[ "$(jq -r '.status.failed // 0' <<<"${job_status}")" -ge 1 ]]; then
    kubectl -n "${namespace}" logs "job/${job_name}" --request-timeout="${KUBECTL_REQUEST_TIMEOUT}" || true
    echo "::error::Post-deploy smoke Job failed" >&2
    exit 1
  fi
  sleep 5
done

kubectl -n "${namespace}" logs "job/${job_name}" --request-timeout="${KUBECTL_REQUEST_TIMEOUT}" || true
echo "::error::Post-deploy smoke Job exceeded its deadline" >&2
exit 1
