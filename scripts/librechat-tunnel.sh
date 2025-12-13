#!/usr/bin/env bash
#
# Opens an SSM port forwarding tunnel to the LibreChat EC2 instance.
# Access LibreChat at http://localhost:9090 after running.
#
# Usage:
#   ./scripts/librechat-tunnel.sh           # Connect to prod
#   ./scripts/librechat-tunnel.sh -e dev    # Connect to dev
#
set -euo pipefail

# Defaults
ENV="dev"
AWS_REGION="us-east-2"
LOCAL_PORT="${LOCAL_PORT:-9090}"
REMOTE_PORT="${REMOTE_PORT:-3080}"

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

# Validate environment and set profile
if [[ "$ENV" == "dev" ]]; then
    AWS_PROFILE="panw-shifter-dev-workstation"
elif [[ "$ENV" == "prod" ]]; then
    AWS_PROFILE="dev-workstation-user"
else
    echo "Error: Environment must be 'dev' or 'prod'"
    exit 1
fi

INSTANCE_TAG="${ENV}-librechat-ec2"

# Get the LibreChat EC2 instance ID
INSTANCE_ID=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=$INSTANCE_TAG" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].InstanceId' \
  --output text \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE")

if [ "$INSTANCE_ID" == "None" ] || [ -z "$INSTANCE_ID" ]; then
  echo "Error: Could not find running LibreChat EC2 instance for $ENV"
  echo ""
  echo "Possible causes:"
  echo "  - Instance not yet created (run terraform apply)"
  echo "  - Instance stopped or terminated"
  echo ""
  echo "To deploy LibreChat infrastructure:"
  echo "  cd terraform/environments/$ENV/librechat"
  echo "  terraform init && terraform apply"
  exit 1
fi

echo "Starting SSM tunnel to LibreChat EC2..."
echo "  Environment: $ENV"
echo "  Instance:    $INSTANCE_ID"
echo "  Local:       http://localhost:$LOCAL_PORT"
echo "  Remote:      $REMOTE_PORT"
echo ""
echo "Access LibreChat at: http://localhost:$LOCAL_PORT"
echo "Press Ctrl+C to close the tunnel."
echo ""

aws ssm start-session \
  --target "$INSTANCE_ID" \
  --document-name AWS-StartPortForwardingSession \
  --parameters "{\"portNumber\":[\"$REMOTE_PORT\"],\"localPortNumber\":[\"$LOCAL_PORT\"]}" \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE"
