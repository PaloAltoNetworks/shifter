#!/bin/bash
# Deploy GitHub Actions IAM role to dev or prod account
#
# Usage:
#   ./scripts/iam-deploy.sh              # init + plan for dev
#   ./scripts/iam-deploy.sh --apply      # init + apply for dev
#   ./scripts/iam-deploy.sh -e prod      # init + plan for prod
#   ./scripts/iam-deploy.sh -e prod --apply  # init + apply for prod
#
set -euo pipefail

# Defaults
ENV="dev"
ACTION="plan"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -e|--env)
            ENV="$2"
            shift 2
            ;;
        --apply)
            ACTION="apply"
            shift
            ;;
        --destroy)
            ACTION="destroy"
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [-e|--env <dev|prod|all>] [--apply] [--destroy]"
            echo ""
            echo "Options:"
            echo "  -e, --env     Environment: dev (default), prod, or all"
            echo "  --apply       Run terraform apply (default is plan only)"
            echo "  --destroy     Run terraform destroy"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [-e|--env <dev|prod|all>] [--apply] [--destroy]"
            exit 1
            ;;
    esac
done

# Validate environment
if [[ "$ENV" != "dev" && "$ENV" != "prod" && "$ENV" != "proof" && "$ENV" != "all" ]]; then
    echo "Error: Environment must be 'dev', 'prod', 'proof', or 'all'" >&2
    exit 1
fi

# Load profile from .env if not already set
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -f "$REPO_ROOT/.env" ]]; then
    # shellcheck source=/dev/null
    source "$REPO_ROOT/.env"
fi

# Handle 'all' by recursively calling for dev and prod
if [[ "$ENV" == "all" ]]; then
    echo "Deploying to all environments..."
    echo ""
    "$0" -e dev --$ACTION
    echo ""
    echo "=========================================="
    echo ""
    "$0" -e prod --$ACTION
    exit 0
fi

# Set AWS profile and Terraform state bucket based on environment. The bucket
# mirrors the CI deploy secrets (TF_INFRA_STATE_BUCKET_DEV / _PROOF, and
# TF_INFRA_STATE_BUCKET for prod) so this script and the deploy pipeline resolve
# the backend from the same source of truth.
case "$ENV" in
    dev)
        AWS_PROFILE="${PANW_SHIFTER_DEV_PROFILE:?PANW_SHIFTER_DEV_PROFILE not set. Check .env file.}"
        STATE_BUCKET="${TF_INFRA_STATE_BUCKET_DEV:?TF_INFRA_STATE_BUCKET_DEV not set. Check .env file.}"
        ;;
    proof)
        AWS_PROFILE="${PANW_SHIFTER_PROOF_PROFILE:?PANW_SHIFTER_PROOF_PROFILE not set. Check .env file.}"
        STATE_BUCKET="${TF_INFRA_STATE_BUCKET_PROOF:?TF_INFRA_STATE_BUCKET_PROOF not set. Check .env file.}"
        ;;
    prod)
        AWS_PROFILE="${PANW_SHIFTER_PROD_PROFILE:?PANW_SHIFTER_PROD_PROFILE not set. Check .env file.}"
        STATE_BUCKET="${TF_INFRA_STATE_BUCKET:?TF_INFRA_STATE_BUCKET not set. Check .env file.}"
        ;;
esac

echo "=========================================="
echo "IAM Deploy: $ENV environment"
echo "Action: $ACTION"
echo "AWS Profile: $AWS_PROFILE"
echo "=========================================="

cd "$(dirname "$0")/../platform/terraform/global/iam"

# Clean and reinitialize for the target environment
rm -rf .terraform .terraform.lock.hcl

# Render the backend config from the real state bucket. The committed
# <env>.s3.tfbackend files carry a REPLACE_AT_BOOTSTRAP placeholder so
# `terraform validate` works standalone; render_aws_backend_configs.py resolves
# the real bucket/key the same way the CI deploy pipeline does, so this script
# works for any environment without per-run backend edits.
echo ""
echo "Rendering backend config..."
BACKEND_CONFIG_PATH="$(
    AWS_REGION="${AWS_REGION:-us-east-2}" \
        python3 "$REPO_ROOT/scripts/terraform/render_aws_backend_configs.py" \
        --env "$ENV" --bucket "$STATE_BUCKET" --stack global/iam \
        | sed -n 's/^SHIFTER_BACKEND_CONFIG_PATH=//p'
)"
if [[ -z "$BACKEND_CONFIG_PATH" || ! -f "$BACKEND_CONFIG_PATH" ]]; then
    echo "Error: failed to render backend config for $ENV" >&2
    exit 1
fi

echo ""
echo "Initializing terraform..."
AWS_PROFILE="$AWS_PROFILE" terraform init -backend-config="$BACKEND_CONFIG_PATH"

echo ""
case "$ACTION" in
    plan)
        echo "Running terraform plan..."
        AWS_PROFILE="$AWS_PROFILE" terraform plan -var-file="${ENV}.tfvars"
        echo ""
        echo "To apply these changes, run:"
        echo "  $0 -e $ENV --apply"
        ;;
    apply)
        echo "Running terraform apply..."
        AWS_PROFILE="$AWS_PROFILE" terraform apply -var-file="${ENV}.tfvars" -auto-approve
        echo ""
        echo "=========================================="
        echo "IAM role deployed successfully!"
        echo ""
        echo "Role ARN (update GitHub secret AWS_ROLE_ARN${ENV^^}):"
        AWS_PROFILE="$AWS_PROFILE" terraform output github_actions_role_arn
        echo "=========================================="
        ;;
    destroy)
        echo "Running terraform destroy..."
        AWS_PROFILE="$AWS_PROFILE" terraform destroy -var-file="${ENV}.tfvars"
        ;;
    *)
        echo "Error: Unknown action '$ACTION'" >&2
        exit 1
        ;;
esac
