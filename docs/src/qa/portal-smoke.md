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

### 3. Cognito Login (Manual)

1. Open `https://${DOMAIN}/` in browser
2. Verify redirect to Cognito hosted UI
3. Login with test account
4. Verify redirect back to portal dashboard
5. Check session cookie is set

### 4. Admin Interface (Manual)

1. Login as a staff user
2. Navigate to `https://${DOMAIN}/admin/`
3. Verify Django admin loads
4. Check you can view models

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

## Checklist

| Check | Method | Pass Criteria |
|-------|--------|---------------|
| Health check | `curl https://${DOMAIN}/health/` | 200 OK |
| Static assets | `curl https://${DOMAIN}/static/css/styles.css` | 200 OK |
| Cognito redirect | Browser | Redirects to Cognito |
| Login flow | Browser | Can login, session created |
| Admin access | Browser | Admin page loads for staff |
| EC2 running | AWS CLI | Instance state = running |

