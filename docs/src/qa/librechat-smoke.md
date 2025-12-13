# LibreChat Smoke Test

## Setup

```bash
# Dev
export ENV=dev DOMAIN=chat-dev.shifter.keplerops.com AWS_PROFILE=panw-shifter-dev-workstation

# Prod
export ENV=prod DOMAIN=chat.shifter.keplerops.com AWS_PROFILE=dev-workstation-user
```

## CLI Checks (Claude)

```bash
# Get instance
INSTANCE=$(aws ec2 describe-instances --profile $AWS_PROFILE --region us-east-2 \
  --filters "Name=tag:Name,Values=${ENV}-librechat-ec2" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)
echo "Instance: $INSTANCE"

# Health via SSM
aws ssm send-command --profile $AWS_PROFILE --region us-east-2 \
  --instance-ids "$INSTANCE" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["curl -sf http://localhost:3080/api/health && echo OK"]' \
  --query "Command.CommandId" --output text

# Check result (wait 5s)
aws ssm get-command-invocation --profile $AWS_PROFILE --region us-east-2 \
  --command-id "COMMAND_ID" --instance-id "$INSTANCE" \
  --query "Status" --output text
```

## Browser Checks (You)

1. Open `https://${DOMAIN}/`
2. Login/register
3. Send a message, verify Bedrock responds
