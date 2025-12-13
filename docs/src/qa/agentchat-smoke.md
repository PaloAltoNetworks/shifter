# AgentChat Smoke Test

## Setup

```bash
# Dev
export ENV=dev AWS_PROFILE=panw-shifter-dev-workstation

# Prod
export ENV=prod AWS_PROFILE=dev-workstation-user
```

## CLI Checks

```bash
# EC2 running
aws ec2 describe-instances --profile $AWS_PROFILE --region us-east-2 \
  --filters "Name=tag:Name,Values=${ENV}-agentchat-ec2" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text

# Check containers via SSM
INSTANCE_ID=$(aws ec2 describe-instances --profile $AWS_PROFILE --region us-east-2 \
  --filters "Name=tag:Name,Values=${ENV}-agentchat-ec2" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)

aws ssm start-session --target $INSTANCE_ID --profile $AWS_PROFILE --region us-east-2 \
  --document-name AWS-StartInteractiveCommand \
  --parameters command="docker ps"
```

## Browser Checks

1. Start tunnel:
   ```bash
   ./scripts/agentchat-tunnel.sh -e $ENV
   ```

2. Open `http://localhost:3000`

3. Create admin account (first login)

4. Add Bedrock connection:
   - Admin Panel → Settings → Connections
   - Add OpenAI connection:
     - URL: `http://bedrock-gateway:80/api/v1`
     - API Key: `bedrock`
   - Click "Verify Connection"

5. Test chat:
   - Select a Bedrock model from dropdown
   - Send a test message
   - Verify response received

## Expected Results

| Check | Expected |
|-------|----------|
| EC2 instance | Running |
| `open-webui` container | Running |
| `bedrock-gateway` container | Running |
| OpenWebUI loads | Yes |
| Bedrock connection verifies | Yes |
| Chat response | Received from Bedrock |
