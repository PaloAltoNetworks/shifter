#!/bin/bash
set -e

PROFILE="panw-shifter-dev-workstation"
REGION="us-east-2"

echo "=== Finding NGFW instance ==="
# shellcheck disable=SC2016 # Backticks are JMESPath syntax, not shell expansion
NGFW_INFO=$(aws ec2 describe-instances \
  --profile "$PROFILE" \
  --region "$REGION" \
  --filters "Name=tag:Name,Values=*ngfw*" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].[InstanceId,PrivateIpAddress,KeyName,Tags[?Key==`Name`].Value|[0]]' \
  --output text 2>&1)

if [[ -z "$NGFW_INFO" ]] || [[ "$NGFW_INFO" = "None" ]]; then
  echo "ERROR: No running NGFW instance found" >&2
  exit 1
fi

NGFW_ID=$(echo "$NGFW_INFO" | awk '{print $1}')
NGFW_IP=$(echo "$NGFW_INFO" | awk '{print $2}')
KEY_NAME=$(echo "$NGFW_INFO" | awk '{print $3}')
NGFW_NAME=$(echo "$NGFW_INFO" | awk '{print $4}')

echo "NGFW Instance: $NGFW_ID"
echo "NGFW IP: $NGFW_IP"
echo "NGFW Name: $NGFW_NAME"
echo "Key Name: $KEY_NAME"

echo ""
echo "=== Finding SSH key secret ==="
# Extract UUID from key name (format: ngfw-{uuid})
UUID_PREFIX=${KEY_NAME#ngfw-}

# Find the secret with matching UUID
SECRET_ARN=$(aws secretsmanager list-secrets \
  --profile "$PROFILE" \
  --region "$REGION" \
  --output json 2>&1 | jq -r ".SecretList[] | select(.Name | contains(\"ngfw/$UUID_PREFIX\")) | .ARN" | head -1)

if [[ -z "$SECRET_ARN" ]]; then
  echo "ERROR: Could not find SSH key secret for UUID prefix: $UUID_PREFIX" >&2
  exit 1
fi

echo "Secret ARN: $SECRET_ARN"

echo ""
echo "=== Getting SSH key ==="
KEY_CONTENT=$(aws secretsmanager get-secret-value \
  --profile "$PROFILE" \
  --secret-id "$SECRET_ARN" \
  --region "$REGION" \
  --query 'SecretString' \
  --output text 2>&1)

if [[ -z "$KEY_CONTENT" ]]; then
  echo "ERROR: Could not retrieve SSH key" >&2
  exit 1
fi

echo "SSH key retrieved (${#KEY_CONTENT} bytes)"

echo ""
echo "=== Finding portal instance ==="
PORTAL_ID=$(aws ec2 describe-instances \
  --profile "$PROFILE" \
  --region "$REGION" \
  --filters "Name=tag:Name,Values=*portal*" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].InstanceId' \
  --output text 2>&1)

if [[ -z "$PORTAL_ID" ]] || [[ "$PORTAL_ID" = "None" ]]; then
  echo "ERROR: No running portal instance found" >&2
  exit 1
fi

echo "Portal Instance: $PORTAL_ID"

echo ""
echo "=== Running 'show system info' via SSH ==="

# Create temp file with command
TMPFILE=$(mktemp)
cat > "$TMPFILE" << EOF
{
  "commands": [
    "cat > /tmp/ngfw.pem << 'EOFKEY'",
    $(echo "$KEY_CONTENT" | jq -Rs .),
    "EOFKEY",
    "chmod 600 /tmp/ngfw.pem",
    "echo show system info | ssh -i /tmp/ngfw.pem -o StrictHostKeyChecking=yes -o BatchMode=yes -o ConnectTimeout=10 admin@$NGFW_IP 2>&1"
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

  if [[ "$STATUS" != "Pending" ]] && [[ "$STATUS" != "InProgress" ]]; then
    break
  fi
done

echo ""
echo "=== Result (Status: $STATUS) ==="
aws ssm get-command-invocation \
  --profile "$PROFILE" \
  --region "$REGION" \
  --command-id "$CMD_ID" \
  --instance-id "$PORTAL_ID" \
  --query 'StandardOutputContent' \
  --output text 2>&1

if [[ "$STATUS" != "Success" ]]; then
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
