#!/bin/bash
# Fetch environment variables for running the provisioner locally.
#
# This script fetches the same env vars that ECS uses from the task definition
# and outputs them in a format suitable for sourcing or .env files.
#
# Usage:
#   ./scripts/local-provisioner-env.sh -e dev > .env.provisioner
#   source .env.provisioner
#
# Or directly:
#   eval $(./scripts/local-provisioner-env.sh -e dev --export)

set -e

# Defaults
ENV="dev"
REGION="us-east-2"
OUTPUT_FORMAT="env"  # "env" for .env format, "export" for shell export

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -e|--env)
            ENV="$2"
            shift 2
            ;;
        --export)
            OUTPUT_FORMAT="export"
            shift
            ;;
        *)
            echo "Unknown option: $1" >&2
            echo "Usage: $0 [-e|--env <dev|prod>] [--export]" >&2
            exit 1
            ;;
    esac
done

# Validate environment
if [[ "$ENV" != "dev" && "$ENV" != "prod" ]]; then
    echo "Error: Environment must be 'dev' or 'prod'" >&2
    exit 1
fi

# Set profile based on environment
if [[ "$ENV" == "dev" ]]; then
    PROFILE="${PANW_SHIFTER_DEV_PROFILE:-panw-shifter-dev-workstation}"
else
    PROFILE="${PANW_SHIFTER_PROD_PROFILE:-panw-shifter-prod-workstation}"
fi

# Helper to output a variable
output_var() {
    local name="$1"
    local value="$2"
    if [[ "$OUTPUT_FORMAT" == "export" ]]; then
        echo "export ${name}=\"${value}\""
    else
        echo "${name}=${value}"
    fi
}

# Fetch task definition to get env vars
TASK_DEF_ARN=$(aws ecs describe-services \
    --cluster "${ENV}-portal-pulumi" \
    --services "${ENV}-portal-pulumi-provisioner" \
    --region "$REGION" \
    --profile "$PROFILE" \
    --query 'services[0].taskDefinition' \
    --output text 2>/dev/null || echo "")

if [[ -z "$TASK_DEF_ARN" || "$TASK_DEF_ARN" == "None" ]]; then
    # Fallback: list task definitions and get the latest
    TASK_DEF_ARN=$(aws ecs list-task-definitions \
        --family-prefix "${ENV}-portal-pulumi" \
        --region "$REGION" \
        --profile "$PROFILE" \
        --sort DESC \
        --max-items 1 \
        --query 'taskDefinitionArns[0]' \
        --output text 2>/dev/null || echo "")
fi

if [[ -z "$TASK_DEF_ARN" || "$TASK_DEF_ARN" == "None" ]]; then
    echo "Error: Could not find ECS task definition" >&2
    exit 1
fi

# Get task definition details
TASK_DEF=$(aws ecs describe-task-definition \
    --task-definition "$TASK_DEF_ARN" \
    --region "$REGION" \
    --profile "$PROFILE" \
    --query 'taskDefinition.containerDefinitions[0].environment' \
    --output json)

# Parse and output each env var
echo "$TASK_DEF" | jq -r '.[] | "\(.name)=\(.value)"' | while read -r line; do
    name="${line%%=*}"
    value="${line#*=}"
    output_var "$name" "$value"
done

# Add additional vars needed for local dev
output_var "ENVIRONMENT" "$ENV"
output_var "AWS_REGION" "$REGION"
output_var "AWS_PROFILE" "$PROFILE"

# Get RDS endpoint for DB connection
RDS_HOST=$(aws rds describe-db-instances \
    --region "$REGION" \
    --profile "$PROFILE" \
    --query "DBInstances[?DBInstanceIdentifier==\`${ENV}-portal-db\`].Endpoint.Address" \
    --output text)

if [[ -n "$RDS_HOST" && "$RDS_HOST" != "None" ]]; then
    output_var "DB_HOST" "$RDS_HOST"
fi

# Get Pulumi backend URL from SSM or use default
PULUMI_BUCKET=$(aws ssm get-parameter \
    --name "/${ENV}/portal/pulumi-state-bucket" \
    --region "$REGION" \
    --profile "$PROFILE" \
    --query 'Parameter.Value' \
    --output text 2>/dev/null || echo "")

if [[ -n "$PULUMI_BUCKET" && "$PULUMI_BUCKET" != "None" ]]; then
    output_var "PULUMI_BACKEND_URL" "s3://${PULUMI_BUCKET}"
fi

# Secrets provider (KMS)
output_var "PULUMI_SECRETS_PROVIDER" "awskms://alias/${ENV}-range-pulumi-secrets"

echo "" >&2
echo "# Environment variables fetched from ECS task definition" >&2
echo "# Source this file or add to .env" >&2
