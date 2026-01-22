#!/bin/bash
# Get NGFW traffic logs via portal jump host
#
# Usage: ./ngfw-logs.sh [command]
#
# Commands:
#   sessions    - Show active sessions (default)
#   traffic     - Show recent traffic logs
#   rules       - Show security rules
#   config      - Show running config summary
#
# Examples:
#   ./ngfw-logs.sh              # Show active sessions
#   ./ngfw-logs.sh sessions     # Show active sessions
#   ./ngfw-logs.sh traffic      # Show traffic logs
#   ./ngfw-logs.sh rules        # Show security policy rules

set -e

PROFILE="panw-shifter-dev-workstation"
REGION="us-east-2"
COMMAND="${1:-sessions}"

echo "=== Finding NGFW instance ==="
# shellcheck disable=SC2016
NGFW_INFO=$(aws ec2 describe-instances \
  --profile "$PROFILE" \
  --region "$REGION" \
  --filters "Name=tag:Name,Values=*ngfw*" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].[InstanceId,PrivateIpAddress,KeyName,Tags[?Key==`Name`].Value|[0]]' \
  --output text 2>&1)

if [ -z "$NGFW_INFO" ] || [ "$NGFW_INFO" = "None" ]; then
  echo "ERROR: No running NGFW instance found"
  exit 1
fi

NGFW_ID=$(echo "$NGFW_INFO" | awk '{print $1}')
NGFW_IP=$(echo "$NGFW_INFO" | awk '{print $2}')
KEY_NAME=$(echo "$NGFW_INFO" | awk '{print $3}')
NGFW_NAME=$(echo "$NGFW_INFO" | awk '{print $4}')

echo "NGFW Instance: $NGFW_ID"
echo "NGFW IP: $NGFW_IP"
echo "NGFW Name: $NGFW_NAME"

echo ""
echo "=== Getting SSH key ==="
UUID_PREFIX=${KEY_NAME#ngfw-}

SECRET_ARN=$(aws secretsmanager list-secrets \
  --profile "$PROFILE" \
  --region "$REGION" \
  --output json 2>&1 | jq -r ".SecretList[] | select(.Name | contains(\"ngfw/$UUID_PREFIX\")) | .ARN" | head -1)

if [ -z "$SECRET_ARN" ]; then
  echo "ERROR: Could not find SSH key secret for UUID prefix: $UUID_PREFIX"
  exit 1
fi

KEY_CONTENT=$(aws secretsmanager get-secret-value \
  --profile "$PROFILE" \
  --secret-id "$SECRET_ARN" \
  --region "$REGION" \
  --query 'SecretString' \
  --output text 2>&1)

echo "SSH key retrieved"

echo ""
echo "=== Finding portal instance ==="
PORTAL_ID=$(aws ec2 describe-instances \
  --profile "$PROFILE" \
  --region "$REGION" \
  --filters "Name=tag:Name,Values=*portal*" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].InstanceId' \
  --output text 2>&1)

if [ -z "$PORTAL_ID" ] || [ "$PORTAL_ID" = "None" ]; then
  echo "ERROR: No running portal instance found"
  exit 1
fi

echo "Portal Instance: $PORTAL_ID"

# Build the PAN-OS command based on argument
case "$COMMAND" in
  sessions)
    PANOS_CMD="show session all"
    ;;
  traffic)
    # Show traffic logs from last 15 minutes
    PANOS_CMD="show log traffic direction equal backward"
    ;;
  rules)
    PANOS_CMD="show running security-policy"
    ;;
  config)
    PANOS_CMD="show config running"
    ;;
  *)
    # Allow passing custom commands
    PANOS_CMD="$COMMAND"
    ;;
esac

echo ""
echo "=== Running '$PANOS_CMD' ==="

TMPFILE=$(mktemp)
cat > "$TMPFILE" << EOF
{
  "commands": [
    "cat > /tmp/ngfw.pem << 'EOFKEY'",
    $(echo "$KEY_CONTENT" | jq -Rs .),
    "EOFKEY",
    "chmod 600 /tmp/ngfw.pem",
    "echo '$PANOS_CMD' | ssh -i /tmp/ngfw.pem -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=15 admin@$NGFW_IP 2>&1",
    "rm -f /tmp/ngfw.pem"
  ]
}
EOF

CMD_ID=$(aws ssm send-command \
  --profile "$PROFILE" \
  --region "$REGION" \
  --instance-ids "$PORTAL_ID" \
  --document-name AWS-RunShellScript \
  --parameters file://"$TMPFILE" \
  --query 'Command.CommandId' \
  --output text 2>&1)

rm -f "$TMPFILE"

echo "Command ID: $CMD_ID"
echo "Waiting for command to complete..."

# Poll for completion
for _ in {1..30}; do
  sleep 2
  STATUS=$(aws ssm get-command-invocation \
    --profile "$PROFILE" \
    --region "$REGION" \
    --command-id "$CMD_ID" \
    --instance-id "$PORTAL_ID" \
    --query 'Status' \
    --output text 2>&1)

  if [ "$STATUS" != "Pending" ] && [ "$STATUS" != "InProgress" ]; then
    break
  fi
done

echo ""
echo "=== Result (Status: $STATUS) ==="
OUTPUT=$(aws ssm get-command-invocation \
  --profile "$PROFILE" \
  --region "$REGION" \
  --command-id "$CMD_ID" \
  --instance-id "$PORTAL_ID" \
  --query 'StandardOutputContent' \
  --output text 2>&1)

# Filter out SSH warnings and login messages
echo "$OUTPUT" | grep -v "Pseudo-terminal will not be allocated" \
  | grep -v "Warning: Permanently added" \
  | grep -v "Number of failed attempts" \
  | grep -v "failed attempted logins" \
  | grep -v "consider contacting your system administrator"

if [ "$STATUS" != "Success" ]; then
  echo ""
  echo "=== Errors ==="
  aws ssm get-command-invocation \
    --profile "$PROFILE" \
    --region "$REGION" \
    --command-id "$CMD_ID" \
    --instance-id "$PORTAL_ID" \
    --query 'StandardErrorContent' \
    --output text 2>&1
fi
