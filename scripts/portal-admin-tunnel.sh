#!/usr/bin/env bash
#
# Opens an SSM port forwarding tunnel to the portal EC2 for admin access.
# Access Django admin at http://localhost:9000/admin/ after running.
#
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-2}"
AWS_PROFILE="${AWS_PROFILE:-dev-workstation-user}"
LOCAL_PORT="${LOCAL_PORT:-9000}"
REMOTE_PORT="${REMOTE_PORT:-8000}"

# Get the portal EC2 instance ID
INSTANCE_ID=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=prod-portal-ec2" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].InstanceId' \
  --output text \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE")

if [ "$INSTANCE_ID" == "None" ] || [ -z "$INSTANCE_ID" ]; then
  echo "Error: Could not find running portal EC2 instance"
  echo "The instance may be stopped (scheduled off 10pm-6am PST)"
  exit 1
fi

echo "Starting SSM tunnel to portal EC2..."
echo "  Instance: $INSTANCE_ID"
echo "  Local:    http://localhost:$LOCAL_PORT"
echo "  Remote:   $REMOTE_PORT"
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
