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
if [[ "$ENV" != "dev" && "$ENV" != "prod" && "$ENV" != "all" ]]; then
    echo "Error: Environment must be 'dev', 'prod', or 'all'"
    exit 1
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

# Set AWS profile based on environment
if [[ "$ENV" == "dev" ]]; then
    AWS_PROFILE="${PANW_SHIFTER_DEV_PROFILE:-panw-shifter-dev-workstation}"
else
    AWS_PROFILE="${PANW_SHIFTER_PROD_PROFILE:-dev-workstation-user}"
fi

echo "=========================================="
echo "IAM Deploy: $ENV environment"
echo "Action: $ACTION"
echo "AWS Profile: $AWS_PROFILE"
echo "=========================================="

cd "$(dirname "$0")/../terraform/global/iam"

# Clean and reinitialize for the target environment
rm -rf .terraform .terraform.lock.hcl

echo ""
echo "Initializing terraform..."
AWS_PROFILE="$AWS_PROFILE" terraform init -backend-config="${ENV}.s3.tfbackend"

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
        echo "Error: Unknown action '$ACTION'"
        exit 1
        ;;
esac
