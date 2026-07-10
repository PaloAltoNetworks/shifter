#!/usr/bin/env bash
# Post-deploy live range smoke (issue #218).
#
# Runs ``python manage.py run_post_deploy_smoke`` inside the deployed portal
# container via SSM. Requires AWS credentials, portal SSM access, and env vars
# documented in scripts/post_deploy_smoke/README.md.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

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

ENVIRONMENT="${ENV:-dev}"
TERRAFORM_DIR="${TERRAFORM_DIR:-${REPO_ROOT}/platform/terraform/environments/${ENVIRONMENT}/portal}"
BACKEND_CONFIG="${SHIFTER_BACKEND_CONFIG_PATH:-${REPO_ROOT}/platform/terraform/environments/${ENVIRONMENT}/portal/backend.hcl}"
INSTANCE_TAG="${PORTAL_INSTANCE_TAG:-${ENVIRONMENT}-portal}"

if [[ -z "${SMOKE_TEST_USER_EMAIL:-}" ]]; then
  echo "::error::SMOKE_TEST_USER_EMAIL is required" >&2
  exit 1
fi

TOPO_FILE="$(mktemp)"
trap 'rm -f "${TOPO_FILE}"' EXIT

python3 "${REPO_ROOT}/scripts/portal_deploy/portal_deploy.py" resolve-topology \
  --terraform-dir "${TERRAFORM_DIR}" \
  --backend-config "${BACKEND_CONFIG}" \
  --instance-tag "${INSTANCE_TAG}" \
  --github-output "${TOPO_FILE}"

# shellcheck disable=SC1090
source "${TOPO_FILE}"

RUN_ARGS=(run_post_deploy_smoke --variant "${VARIANT}")

# The manage command runs inside the portal container via `docker exec`, which
# does not inherit this job's environment. Forward every SMOKE_* value the
# command reads (the user identity plus the per-variant agent IDs) explicitly
# with --env; skip any that are unset so we never pass empty overrides.
ENV_ARGS=()
for smoke_var in SMOKE_TEST_USER_EMAIL SMOKE_LINUX_AGENT_ID SMOKE_WINDOWS_AGENT_ID; do
  smoke_val="${!smoke_var:-}"
  if [[ -n "${smoke_val}" ]]; then
    ENV_ARGS+=(--env "${smoke_var}=${smoke_val}")
  fi
done

if [[ -n "${instance_id:-}" ]]; then
  python3 "${REPO_ROOT}/scripts/portal_deploy/portal_deploy.py" run-manage-on-portal \
    --instance-id "${instance_id}" \
    "${ENV_ARGS[@]}" \
    "${RUN_ARGS[@]}"
elif [[ -n "${asg_name:-}" ]]; then
  python3 "${REPO_ROOT}/scripts/portal_deploy/portal_deploy.py" run-manage-on-portal \
    --asg-name "${asg_name}" \
    "${ENV_ARGS[@]}" \
    "${RUN_ARGS[@]}"
else
  echo "::error::resolve-topology did not emit instance_id or asg_name" >&2
  exit 1
fi
