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
#   - PANW_SHIFTER_DEV_PROFILE set in .env (AWS profile for dev account)
#
# Post-apply: each EC2 runner needs to be registered with the repo manually:
#   1. Generate a registration token:
#        gh api -X POST /repos/<org>/<repo>/actions/runners/registration-token --jq .token
#   2. SSM into the runner (terraform output ssm_commands shows the commands)
#   3. As ec2-user, run:
#        cd /home/ec2-user/actions-runner
#        ./config.sh --url https://github.com/<org>/<repo> --token <TOKEN> \
#          --labels self-hosted,linux,X64 --unattended --replace
#        sudo ./svc.sh install ec2-user
#        sudo ./svc.sh start
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
            echo "Post-apply: register each runner manually with the repo via SSM."
            echo "See top-of-file comment for the registration commands."
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--apply] [--destroy]"
            exit 1
            ;;
    esac
done

# Load profile from .env if not already set
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -f "$REPO_ROOT/.env" ]]; then
    # shellcheck source=/dev/null
    source "$REPO_ROOT/.env"
fi

# Always use dev profile - runners live in dev account
AWS_PROFILE="${PANW_SHIFTER_DEV_PROFILE:?PANW_SHIFTER_DEV_PROFILE not set. Check .env file.}"

echo "=========================================="
echo "GitHub Runner Deploy"
echo "Action: $ACTION"
echo "AWS Profile: $AWS_PROFILE"
echo "=========================================="

cd "$(dirname "$0")/../platform/terraform/global/github-runner"

# Clean local terraform plugin cache; KEEP the lockfile so providers stay pinned.
rm -rf .terraform/

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
        echo "Runner instance IDs:"
        AWS_PROFILE="$AWS_PROFILE" terraform output runner_instance_ids
        echo ""
        echo "SSM connect commands:"
        AWS_PROFILE="$AWS_PROFILE" terraform output ssm_commands
        echo ""
        echo "Next: register each runner with the repo (see top-of-file comment"
        echo "for the exact registration commands)."
        echo "=========================================="
        ;;
    destroy)
        echo "Running terraform destroy..."
        AWS_PROFILE="$AWS_PROFILE" terraform destroy -var-file="dev.tfvars"
        ;;
    *)
        echo "Error: Unknown action '$ACTION'" >&2
        exit 1
        ;;
esac
