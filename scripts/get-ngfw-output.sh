#!/bin/bash
# Quick script to get raw NGFW SSH output

PROFILE="${AWS_PROFILE:-panw-shifter-dev-workstation}"
REGION="us-east-2"
NGFW_IP="10.1.7.97"
PORTAL_ID="i-0e3a1f17656fa3162"
SECRET_ARN="arn:aws:secretsmanager:us-east-2:878848911818:secret:shifter/dev/ngfw/90bf3459-ad92-4173-b4f2-12adba345023/ssh-key-zMD2HM"

echo "Getting SSH key..."
KEY_CONTENT=$(aws secretsmanager get-secret-value \
  --profile "$PROFILE" \
  --secret-id "$SECRET_ARN" \
  --region "$REGION" \
  --query 'SecretString' \
  --output text 2>&1)

echo "Sending SSH command..."
TMPFILE=$(mktemp)
cat > "$TMPFILE" << EOF
{
  "commands": [
    "cat > /tmp/ngfw.pem << 'EOFKEY'",
    $(echo "$KEY_CONTENT" | jq -Rs .),
    "EOFKEY",
    "chmod 600 /tmp/ngfw.pem",
    "ssh -i /tmp/ngfw.pem -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10 admin@$NGFW_IP show system info 2>&1 | cat -A"
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
echo "Waiting..."

for i in {1..30}; do
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
echo "=== Raw Output (with cat -A to show control chars) ==="
aws ssm get-command-invocation \
  --profile "$PROFILE" \
  --region "$REGION" \
  --command-id "$CMD_ID" \
  --instance-id "$PORTAL_ID" \
  --query 'StandardOutputContent' \
  --output text 2>&1
