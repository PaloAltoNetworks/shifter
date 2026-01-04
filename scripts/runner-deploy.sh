#!/bin/bash
# Deploy GitHub Actions self-hosted runner infrastructure
#
# Runners are deployed ONCE in the dev account but have cross-account access
# to deploy infrastructure to both dev and prod environments.
#
# Usage:
#   ./scripts/runner-deploy.sh              # init + plan
#   ./scripts/runner-deploy.sh --apply      # init + apply
#   ./scripts/runner-deploy.sh --destroy    # destroy
#
# Prerequisites:
#   - GitHub App created with required permissions
#   - SSM parameters created:
#     /shifter/github-runner/key-base64 (base64-encoded private key)
#     /shifter/github-runner/webhook-secret
#
set -euo pipefail

# Defaults
ACTION="plan"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --apply)
            ACTION="apply"
            shift
            ;;
        --destroy)
            ACTION="destroy"
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [--apply] [--destroy]"
            echo ""
            echo "Options:"
            echo "  --apply       Run terraform apply (default is plan only)"
            echo "  --destroy     Run terraform destroy"
            echo ""
            echo "Note: Runners deploy to dev account only but have cross-account"
            echo "      access to deploy to both dev and prod environments."
            echo ""
            echo "Prerequisites:"
            echo "  Create SSM parameters before first deploy:"
            echo "    /shifter/github-runner/key-base64"
            echo "    /shifter/github-runner/webhook-secret"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--apply] [--destroy]"
            exit 1
            ;;
    esac
done

# Always use dev profile - runners live in dev account
AWS_PROFILE="${PANW_SHIFTER_DEV_PROFILE:-panw-shifter-dev-workstation}"

echo "=========================================="
echo "GitHub Runner Deploy"
echo "Action: $ACTION"
echo "AWS Profile: $AWS_PROFILE"
echo "=========================================="

cd "$(dirname "$0")/../platform/terraform/global/github-runner"

# Clean and reinitialize
rm -rf .terraform .terraform.lock.hcl

echo ""
echo "Initializing terraform..."
AWS_PROFILE="$AWS_PROFILE" terraform init -backend-config="dev.s3.tfbackend"

echo ""
case "$ACTION" in
    plan)
        echo "Running terraform plan..."
        AWS_PROFILE="$AWS_PROFILE" terraform plan -var-file="dev.tfvars"
        echo ""
        echo "To apply these changes, run:"
        echo "  $0 --apply"
        ;;
    apply)
        echo "Running terraform apply..."
        AWS_PROFILE="$AWS_PROFILE" terraform apply -var-file="dev.tfvars" -auto-approve
        echo ""
        echo "=========================================="
        echo "GitHub Runner infrastructure deployed!"
        echo ""
        echo "Webhook endpoint (configure in GitHub App):"
        AWS_PROFILE="$AWS_PROFILE" terraform output webhook_endpoint
        echo ""
        echo "Runner labels:"
        AWS_PROFILE="$AWS_PROFILE" terraform output runner_labels
        echo ""
        echo "Next steps:"
        echo "  1. Go to GitHub App settings → Webhook"
        echo "  2. Enable webhook"
        echo "  3. Paste the webhook URL above"
        echo "  4. Enter the webhook secret (from .env or SSM)"
        echo "  5. Subscribe to events: check 'Workflow Job' only"
        echo "  6. Install the app on your repository"
        echo "=========================================="
        ;;
    destroy)
        echo "Running terraform destroy..."
        AWS_PROFILE="$AWS_PROFILE" terraform destroy -var-file="dev.tfvars"
        ;;
    *)
        echo "Error: Unknown action '$ACTION'"
        exit 1
        ;;
esac
