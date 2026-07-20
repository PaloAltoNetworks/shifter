#!/usr/bin/env bash
# Delete a portal test user from Cognito and Django (issue #83).
#
# Usage:
#   ./scripts/delete-user.sh user@example.com
#   ./scripts/delete-user.sh --env dev user@example.com
#   AWS_PROFILE=my-profile ./scripts/delete-user.sh user@example.com
#   ./scripts/delete-user.sh --profile my-profile user@example.com
#
# Requires AWS credentials with Cognito admin access and SSM access to the portal EC2.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

ENVIRONMENT="${ENV:-dev}"
AWS_REGION="${AWS_REGION:-us-east-2}"
TERRAFORM_DIR="${TERRAFORM_DIR:-${REPO_ROOT}/platform/terraform/environments/${ENVIRONMENT}/portal}"
BACKEND_CONFIG="${SHIFTER_BACKEND_CONFIG_PATH:-${REPO_ROOT}/platform/terraform/environments/${ENVIRONMENT}/portal/backend.hcl}"
INSTANCE_TAG="${PORTAL_INSTANCE_TAG:-${ENVIRONMENT}-portal}"
USER_EMAIL=""

usage() {
  cat <<EOF
Usage: $0 [--env dev|prod] [--profile AWS_PROFILE] <email>

Delete a test user from Cognito and Django.

Options:
  --env, -e       Portal environment (default: dev)
  --profile, -p   AWS profile (default: AWS_PROFILE or .env PANW_SHIFTER_* profile)
  -h, --help      Show this help

Examples:
  $0 bedwards@paloaltonetworks.com
  $0 --env dev --profile my-dev-profile bedwards@paloaltonetworks.com
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -e | --env)
      ENVIRONMENT="${2:?--env requires a value}"
      TERRAFORM_DIR="${REPO_ROOT}/platform/terraform/environments/${ENVIRONMENT}/portal"
      BACKEND_CONFIG="${REPO_ROOT}/platform/terraform/environments/${ENVIRONMENT}/portal/backend.hcl"
      INSTANCE_TAG="${ENVIRONMENT}-portal"
      shift 2
      ;;
    -p | --profile)
      AWS_PROFILE="${2:?--profile requires a value}"
      shift 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    -*)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      if [[ -n "${USER_EMAIL}" ]]; then
        echo "Unexpected extra argument: $1" >&2
        usage >&2
        exit 2
      fi
      USER_EMAIL="$1"
      shift
      ;;
  esac
done

if [[ -z "${USER_EMAIL}" ]]; then
  echo "Error: email argument is required" >&2
  usage >&2
  exit 1
fi

if [[ -f "${REPO_ROOT}/.env" ]]; then
  # shellcheck source=/dev/null
  source "${REPO_ROOT}/.env"
fi

if [[ -z "${AWS_PROFILE:-}" ]]; then
  if [[ "${ENVIRONMENT}" == "prod" ]]; then
    AWS_PROFILE="${PANW_SHIFTER_PROD_PROFILE:-}"
  else
    AWS_PROFILE="${PANW_SHIFTER_DEV_PROFILE:-}"
  fi
fi

if [[ -z "${AWS_PROFILE}" ]]; then
  echo "Error: set AWS_PROFILE or pass --profile (or configure PANW_SHIFTER_* in .env)" >&2
  exit 1
fi

if [[ "${ENVIRONMENT}" == "prod" ]]; then
  echo "WARNING: deleting a user in prod environment (${USER_EMAIL})" >&2
  read -r -p "Type the email address again to confirm prod deletion: " confirm_email
  if [[ "${confirm_email}" != "${USER_EMAIL}" ]]; then
    echo "Confirmation failed; aborting" >&2
    exit 1
  fi
fi

export AWS_PROFILE AWS_REGION

terraform -chdir="${TERRAFORM_DIR}" init -backend-config="${BACKEND_CONFIG}" >/dev/null
POOL_ID="$(terraform -chdir="${TERRAFORM_DIR}" output -raw cognito_user_pool_id)"

echo "Deleting Cognito user pool=${POOL_ID} username=${USER_EMAIL}"
set +e
delete_err="$(
  aws cognito-idp admin-delete-user \
    --user-pool-id "${POOL_ID}" \
    --username "${USER_EMAIL}" \
    --region "${AWS_REGION}" \
    --profile "${AWS_PROFILE}" 2>&1
)"
delete_status=$?
set -e

if [[ "${delete_status}" -eq 0 ]]; then
  :
elif [[ "${delete_err}" == *"UserNotFoundException"* ]]; then
  echo "Cognito user not found; continuing"
else
  set +e
  get_err="$(
    aws cognito-idp admin-get-user \
      --user-pool-id "${POOL_ID}" \
      --username "${USER_EMAIL}" \
      --region "${AWS_REGION}" \
      --profile "${AWS_PROFILE}" 2>&1
  )"
  get_status=$?
  set -e
  if [[ "${get_status}" -eq 0 ]]; then
    echo "Error: Cognito delete failed (exit ${delete_status})" >&2
    exit "${delete_status}"
  fi
  if [[ "${get_err}" == *"UserNotFoundException"* ]]; then
    echo "Cognito user not found; continuing"
  else
    echo "Error: Cognito delete failed (exit ${delete_status})" >&2
    exit "${delete_status}"
  fi
fi

TOPO_FILE="$(mktemp)"
trap 'rm -f "${TOPO_FILE}"' EXIT

python3 "${REPO_ROOT}/scripts/portal_deploy/portal_deploy.py" resolve-topology \
  --terraform-dir "${TERRAFORM_DIR}" \
  --backend-config "${BACKEND_CONFIG}" \
  --instance-tag "${INSTANCE_TAG}" \
  --github-output "${TOPO_FILE}"

instance_id=""
asg_name=""
while IFS='=' read -r topo_key topo_value; do
  case "${topo_key}" in
    instance_id)
      if [[ ! "${topo_value}" =~ ^i-[0-9a-f]+$ ]]; then
        echo "Error: invalid instance_id from resolve-topology" >&2
        exit 1
      fi
      instance_id="${topo_value}"
      ;;
    asg_name)
      if [[ ! "${topo_value}" =~ ^[A-Za-z0-9._-]+$ ]]; then
        echo "Error: invalid asg_name from resolve-topology" >&2
        exit 1
      fi
      asg_name="${topo_value}"
      ;;
  esac
done < "${TOPO_FILE}"

echo "Deleting Django user email=${USER_EMAIL}"
if [[ -n "${instance_id:-}" ]]; then
  python3 "${REPO_ROOT}/scripts/portal_deploy/portal_deploy.py" run-manage-on-portal \
    --instance-id "${instance_id}" \
    delete_user "${USER_EMAIL}"
elif [[ -n "${asg_name:-}" ]]; then
  python3 "${REPO_ROOT}/scripts/portal_deploy/portal_deploy.py" run-manage-on-portal \
    --asg-name "${asg_name}" \
    delete_user "${USER_EMAIL}"
else
  echo "Error: resolve-topology did not emit instance_id or asg_name" >&2
  exit 1
fi

echo "Done."
