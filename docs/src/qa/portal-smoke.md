# Portal Smoke Test

## Setup

```bash
# Dev
export ENV=dev DOMAIN=dev.shifter.keplerops.com AWS_PROFILE=panw-shifter-dev-workstation

# Prod
export ENV=prod DOMAIN=shifter.keplerops.com AWS_PROFILE=dev-workstation-user
```

## CLI Checks (Claude)

```bash
# Health
curl -sf "https://${DOMAIN}/health/" && echo "OK" || echo "FAIL"

# EC2 running
aws ec2 describe-instances --profile $AWS_PROFILE --region us-east-2 \
  --filters "Name=tag:Name,Values=${ENV}-portal-ec2" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text
```

## Browser Checks (You)

1. Open `https://${DOMAIN}/`
2. Cognito redirect → login
3. Dashboard loads
