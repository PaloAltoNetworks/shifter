#!/usr/bin/env bash
#
# Opens an SSM port forwarding tunnel to the LibreChat EC2 instance.
# Access LibreChat at http://localhost:9090 after running.
#
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-2}"
AWS_PROFILE="${AWS_PROFILE:-dev-workstation-user}"
LOCAL_PORT="${LOCAL_PORT:-9090}"
REMOTE_PORT="${REMOTE_PORT:-3080}"

# Get the LibreChat EC2 instance ID
INSTANCE_ID=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=prod-librechat-ec2" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].InstanceId' \
  --output text \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE")

if [ "$INSTANCE_ID" == "None" ] || [ -z "$INSTANCE_ID" ]; then
  echo "Error: Could not find running LibreChat EC2 instance"
  echo ""
  echo "Possible causes:"
  echo "  - Instance not yet created (run terraform apply)"
  echo "  - Instance stopped or terminated"
  echo ""
  echo "To deploy LibreChat infrastructure:"
  echo "  cd terraform/environments/prod/librechat"
  echo "  terraform init && terraform apply"
  exit 1
fi

echo "Starting SSM tunnel to LibreChat EC2..."
echo "  Instance: $INSTANCE_ID"
echo "  Local:    http://localhost:$LOCAL_PORT"
echo "  Remote:   $REMOTE_PORT"
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

