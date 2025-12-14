#!/usr/bin/env bash
#
# Opens an SSM port forwarding tunnel to the portal EC2 for admin access.
# Access Django admin at http://localhost:9000/admin/ after running.
#
# Usage:
#   ./scripts/portal-admin-tunnel.sh           # Connect to dev (default)
#   ./scripts/portal-admin-tunnel.sh -e prod   # Connect to prod
#
set -euo pipefail

# Defaults
ENV="dev"
AWS_REGION="${AWS_REGION:-us-east-2}"
LOCAL_PORT="${LOCAL_PORT:-9000}"
REMOTE_PORT="${REMOTE_PORT:-8000}"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -e|--env)
            ENV="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [-e|--env <dev|prod>]"
            exit 1
            ;;
    esac
done

# Validate environment
if [[ "$ENV" != "dev" && "$ENV" != "prod" ]]; then
    echo "Error: Environment must be 'dev' or 'prod'"
    exit 1
fi

# Set profile based on environment
if [[ "$ENV" == "dev" ]]; then
    AWS_PROFILE="$PANW_SHIFTER_DEV_PROFILE"
else
    AWS_PROFILE="$PANW_SHIFTER_PROD_PROFILE"
fi

INSTANCE_TAG="${ENV}-portal-ec2"

# Get the portal EC2 instance ID
INSTANCE_ID=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=$INSTANCE_TAG" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].InstanceId' \
  --output text \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE")

if [ "$INSTANCE_ID" == "None" ] || [ -z "$INSTANCE_ID" ]; then
  echo "Error: Could not find running portal EC2 instance for $ENV"
  echo "The instance may be stopped (scheduled off 10pm-6am PST)"
  exit 1
fi

echo "Starting SSM tunnel to portal EC2..."
echo "  Environment: $ENV"
echo "  Instance:    $INSTANCE_ID"
echo "  Local:       http://localhost:$LOCAL_PORT"
echo "  Remote:      $REMOTE_PORT"
echo ""
echo "Access Django admin at: http://localhost:$LOCAL_PORT/admin/"
echo "Press Ctrl+C to close the tunnel."
echo ""

aws ssm start-session \
  --target "$INSTANCE_ID" \
  --document-name AWS-StartPortForwardingSession \
  --parameters "{\"portNumber\":[\"$REMOTE_PORT\"],\"localPortNumber\":[\"$LOCAL_PORT\"]}" \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE"
