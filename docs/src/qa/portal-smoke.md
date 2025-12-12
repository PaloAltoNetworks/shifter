# Portal Smoke Test

Verify the Django portal is functioning correctly.

## Prerequisites

- Portal infrastructure deployed
- DNS configured and ACM cert validated
- AWS CLI configured with appropriate profile

## Environment Setup

```bash
export ENV=dev  # or prod
export DOMAIN="shifter.keplerops.com"  # adjust for env
[ "$ENV" == "dev" ] && DOMAIN="dev.shifter.keplerops.com"
```

## Checks

### 1. Health Check

```bash
curl -sf "https://${DOMAIN}/health/" && echo "PASS: Health check" || echo "FAIL: Health check"
```

Expected: HTTP 200, response body contains health status.

### 2. Static Assets

```bash
curl -sf "https://${DOMAIN}/static/css/styles.css" -o /dev/null && echo "PASS: Static assets" || echo "FAIL: Static assets"
```

Expected: HTTP 200.

### 3. Cognito Redirect

```bash
REDIRECT=$(curl -sf -o /dev/null -w "%{redirect_url}" "https://${DOMAIN}/")
echo "$REDIRECT" | grep -q "cognito" && echo "PASS: Cognito redirect" || echo "FAIL: Cognito redirect"
```

Expected: Redirects to Cognito hosted UI for unauthenticated users.

### 4. Admin Interface

After logging in as a staff user:

```bash
curl -sf "https://${DOMAIN}/admin/login/" -o /dev/null && echo "PASS: Admin accessible" || echo "FAIL: Admin not accessible"
```

Expected: HTTP 200, Django admin login page loads.

### 5. EC2 Instance Health

```bash
aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=${ENV}-portal-ec2" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].InstanceId' \
  --output text | grep -q "^i-" && echo "PASS: EC2 running" || echo "FAIL: EC2 not running"
```

### 6. Database Connectivity

Implicit in health check. If health check passes, DB is connected.

For explicit verification via SSM:

```bash
INSTANCE_ID=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=${ENV}-portal-ec2" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)

aws ssm start-session --target "$INSTANCE_ID" --document-name AWS-StartInteractiveCommand \
  --parameters command="docker exec portal python manage.py check --database default"
```

## Quick Run

All checks in sequence:

```bash
#!/bin/bash
set -e
ENV=${1:-dev}
DOMAIN="shifter.keplerops.com"
[ "$ENV" == "dev" ] && DOMAIN="dev.shifter.keplerops.com"

echo "Portal Smoke Test - $ENV"
echo "========================"

curl -sf "https://${DOMAIN}/health/" > /dev/null && echo "1. Health check: PASS" || { echo "1. Health check: FAIL"; exit 1; }
curl -sf "https://${DOMAIN}/static/css/styles.css" -o /dev/null && echo "2. Static assets: PASS" || { echo "2. Static assets: FAIL"; exit 1; }
curl -sf "https://${DOMAIN}/admin/login/" -o /dev/null && echo "3. Admin interface: PASS" || { echo "3. Admin interface: FAIL"; exit 1; }

echo "========================"
echo "All checks passed"
```

