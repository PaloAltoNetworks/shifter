#!/bin/bash
set -euo pipefail

STRATEGY="${1:-idle_timeout}"
PROFILE="panw-shifter-dev-workstation"
REGION="us-east-2"

# Get portal instance
PORTAL_ID=$(aws ec2 describe-instances \
  --profile "$PROFILE" \
  --region "$REGION" \
  --filters "Name=tag:Name,Values=*shifter-dev-portal*" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].InstanceId' \
  --output text)

echo "Portal: $PORTAL_ID"

# Get NGFW IP
NGFW_IP=$(aws ec2 describe-instances \
  --profile "$PROFILE" \
  --region "$REGION" \
  --filters "Name=tag:Name,Values=*ngfw*" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].PrivateIpAddress' \
  --output text | head -1)

echo "NGFW: $NGFW_IP"

# Get SSH key
SECRET_ARN=$(aws secretsmanager list-secrets \
  --profile "$PROFILE" \
  --region "$REGION" \
  --output json | jq -r '.SecretList[] | select(.Name | contains("ngfw/79248efb")) | .ARN' | head -1)

KEY_CONTENT=$(aws secretsmanager get-secret-value \
  --profile "$PROFILE" \
  --secret-id "$SECRET_ARN" \
  --region "$REGION" \
  --query 'SecretString' \
  --output text)

KEY_B64=$(echo "$KEY_CONTENT" | base64 -w0)

# Base64 encode the test script
SCRIPT_B64=$(base64 -w0 /tmp/test-strategies.py)

# Create command
TMPFILE=$(mktemp)
cat > "$TMPFILE" << EOFCMD
{
  "commands": [
    "echo '$SCRIPT_B64' | base64 -d > /tmp/test-strat.py",
    "python3 /tmp/test-strat.py '$STRATEGY' '$KEY_B64' '$NGFW_IP'"
  ]
}
EOFCMD

echo "Running $STRATEGY test via SSM..."

CMD_ID=$(aws ssm send-command \
  --profile "$PROFILE" \
  --region "$REGION" \
  --instance-ids "$PORTAL_ID" \
  --document-name AWS-RunShellScript \
  --parameters file://"$TMPFILE" \
  --query 'Command.CommandId' \
  --output text)

rm -f "$TMPFILE"

echo "Command ID: $CMD_ID"
echo "Waiting for result..."
sleep 5

aws ssm get-command-invocation \
  --profile "$PROFILE" \
  --region "$REGION" \
  --command-id "$CMD_ID" \
  --instance-id "$PORTAL_ID" \
  --query '[Status,StandardOutputContent,StandardErrorContent]' \
  --output text
