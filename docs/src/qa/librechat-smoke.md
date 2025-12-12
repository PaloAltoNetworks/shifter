# LibreChat Smoke Test

Verify LibreChat is functioning correctly with Bedrock integration.

## Prerequisites

- LibreChat infrastructure deployed
- Portal deployed (LibreChat uses Portal VPC)
- AWS CLI configured with appropriate profile

## Environment Setup

```bash
export ENV=dev  # or prod
export AWS_PROFILE=panw-shifter-${ENV}-workstation
export AWS_REGION=us-east-2
```

## Checks

### 1. EC2 Instance Running

```bash
INSTANCE_ID=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=${ENV}-librechat-ec2" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)

[ "$INSTANCE_ID" != "None" ] && echo "PASS: EC2 running ($INSTANCE_ID)" || echo "FAIL: EC2 not running"
```

### 2. Docker Containers Running

```bash
COMMAND_ID=$(aws ssm send-command \
  --document-name "AWS-RunShellScript" \
  --instance-ids "$INSTANCE_ID" \
  --parameters 'commands=["docker compose -f /opt/librechat/docker-compose.yml ps --format json"]' \
  --query "Command.CommandId" --output text)

sleep 5

aws ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" \
  --query "StandardOutputContent" --output text
```

Expected: Shows `librechat` and `mongodb` containers as running.

### 3. Health Check (via SSM)

```bash
COMMAND_ID=$(aws ssm send-command \
  --document-name "AWS-RunShellScript" \
  --instance-ids "$INSTANCE_ID" \
  --parameters 'commands=["curl -sf http://localhost:3080/api/health"]' \
  --query "Command.CommandId" --output text)

sleep 3

RESULT=$(aws ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" \
  --query "Status" --output text)

[ "$RESULT" == "Success" ] && echo "PASS: Health check" || echo "FAIL: Health check"
```

### 4. Secrets Configured

```bash
SECRET_ARN=$(aws secretsmanager list-secrets \
  --filters Key=name,Values="shifter-${ENV}-librechat" \
  --query 'SecretList[0].ARN' --output text)

[ "$SECRET_ARN" != "None" ] && echo "PASS: Secrets exist" || echo "FAIL: Secrets not found"
```

### 5. Bedrock Access (via SSM)

Test that the instance can call Bedrock:

```bash
COMMAND_ID=$(aws ssm send-command \
  --document-name "AWS-RunShellScript" \
  --instance-ids "$INSTANCE_ID" \
  --parameters 'commands=["aws bedrock-runtime invoke-model --model-id us.anthropic.claude-3-haiku-20240307-v1:0 --body '\''{\"anthropic_version\":\"bedrock-2023-05-31\",\"max_tokens\":10,\"messages\":[{\"role\":\"user\",\"content\":\"Hi\"}]}'\'' --region us-east-2 /dev/null && echo BEDROCK_OK"]' \
  --query "Command.CommandId" --output text)

sleep 5

aws ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" \
  --query "StandardOutputContent" --output text | grep -q "BEDROCK_OK" \
  && echo "PASS: Bedrock accessible" || echo "FAIL: Bedrock not accessible"
```

### 6. Chat Test (Manual)

1. Access LibreChat at `https://chat.${DOMAIN}/` (or via SSH tunnel to port 3080)
2. Register or login with email/password
3. Select a Bedrock model (Claude Sonnet recommended)
4. Start a new chat
5. Send: "Respond with just the word OK"
6. Verify you get a response (confirms Bedrock integration works)

If no response or error:
- Check EC2 instance profile has `bedrock:InvokeModel` permission
- Check CloudWatch logs for the LibreChat container

## Quick Run

```bash
#!/bin/bash
set -e
ENV=${1:-dev}
export AWS_PROFILE=panw-shifter-${ENV}-workstation
export AWS_REGION=us-east-2

echo "LibreChat Smoke Test - $ENV"
echo "============================"

INSTANCE_ID=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=${ENV}-librechat-ec2" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)

[ "$INSTANCE_ID" == "None" ] && { echo "FAIL: EC2 not running"; exit 1; }
echo "1. EC2 running: PASS ($INSTANCE_ID)"

# Health check
COMMAND_ID=$(aws ssm send-command \
  --document-name "AWS-RunShellScript" \
  --instance-ids "$INSTANCE_ID" \
  --parameters 'commands=["curl -sf http://localhost:3080/api/health && echo OK"]' \
  --query "Command.CommandId" --output text)
sleep 5
STATUS=$(aws ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --query "Status" --output text)
[ "$STATUS" == "Success" ] && echo "2. Health check: PASS" || { echo "2. Health check: FAIL"; exit 1; }

# Secrets
SECRET_ARN=$(aws secretsmanager list-secrets --filters Key=name,Values="shifter-${ENV}-librechat" --query 'SecretList[0].ARN' --output text)
[ "$SECRET_ARN" != "None" ] && echo "3. Secrets configured: PASS" || { echo "3. Secrets: FAIL"; exit 1; }

echo "============================"
echo "All checks passed"
echo "Manual test: Login and send a chat message to verify Bedrock integration"
```

## Troubleshooting

| Issue | Check |
|-------|-------|
| Health check fails | `docker compose logs librechat` |
| Bedrock errors | Check IAM instance profile has bedrock:InvokeModel |
| MongoDB errors | `docker compose logs mongodb` |
| Container not starting | Check `/opt/librechat/.env` exists and has correct values |

