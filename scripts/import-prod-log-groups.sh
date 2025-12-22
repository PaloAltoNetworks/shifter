#!/bin/bash
# Import existing CloudWatch Log Groups into Terraform state
# These log groups were auto-created by Lambda before Terraform could create them

set -e

export AWS_REGION="us-east-2"
export AWS_PROFILE="dev-workstation-user"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORTAL_DIR="${SCRIPT_DIR}/../terraform/environments/prod/portal"

cd "$PORTAL_DIR"
echo "Working directory: $(pwd)"
echo "AWS Profile: $AWS_PROFILE"
echo "AWS Region: $AWS_REGION"
echo ""

echo "Importing Cognito pre-signup log group..."
terraform import 'module.cognito.aws_cloudwatch_log_group.pre_signup' '/aws/lambda/prod-portal-cognito-pre-signup'

echo "Importing provisioner log groups..."
terraform import 'module.provisioner.aws_cloudwatch_log_group.create_subnet' '/aws/lambda/prod-portal-create-subnet'
terraform import 'module.provisioner.aws_cloudwatch_log_group.create_victim' '/aws/lambda/prod-portal-create-victim'
terraform import 'module.provisioner.aws_cloudwatch_log_group.create_kali' '/aws/lambda/prod-portal-create-kali'
terraform import 'module.provisioner.aws_cloudwatch_log_group.mark_ready' '/aws/lambda/prod-portal-mark-ready'
terraform import 'module.provisioner.aws_cloudwatch_log_group.verify_agent' '/aws/lambda/prod-portal-verify-agent'
terraform import 'module.provisioner.aws_cloudwatch_log_group.cleanup' '/aws/lambda/prod-portal-cleanup'
terraform import 'module.provisioner.aws_cloudwatch_log_group.find_stale_ranges' '/aws/lambda/prod-portal-find-stale-ranges'

echo ""
echo "All imports complete. Run 'terraform plan' to verify state."
