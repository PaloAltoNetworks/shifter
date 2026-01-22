---
name: aws-logs
description: Query AWS CloudWatch logs for Shifter components. Use when investigating provisioner issues, portal errors, range problems, or any AWS infrastructure debugging.
---

# AWS Logs Reference

Query CloudWatch logs for Shifter platform components.

## Log Groups by Component

### Portal/Platform Application
- **Log Group**: `/portal/dev-portal` (dev) / `/portal/prod-portal` (prod)
- **Use for**: Django app errors, startup issues, worker logs
- **Stream format**: Container ID hash

### Pulumi Provisioner (Range/NGFW)
- **Log Group**: `/ecs/dev-portal-pulumi-provisioner`
- **Use for**: Range provisioning, NGFW provisioning, Pulumi stack operations
- **Stream format**: `pulumi/pulumi-provisioner/<task-id>`

### Guacamole
- **Log Groups**:
  - `/ecs/dev-portal-guacamole-client`
  - `/ecs/dev-portal-guacd`
- **Use for**: Remote desktop connection issues

### Network Firewall
- **Log Group**: `/aws/network-firewall/dev-range`
- **Use for**: Network traffic blocked/allowed, firewall rule issues

### RDS Database
- **Log Group**: `/aws/rds/instance/dev-portal-db/postgresql`
- **Use for**: Database errors, slow queries

## Quick Commands

### Get Latest Provisioner Logs

```bash
PROFILE="panw-shifter-dev-workstation"
REGION="us-east-2"

STREAM=$(aws logs describe-log-streams \
  --log-group-name /ecs/dev-portal-pulumi-provisioner \
  --order-by LastEventTime --descending --limit 1 \
  --query 'logStreams[0].logStreamName' --output text \
  --region "$REGION" --profile "$PROFILE")

aws logs get-log-events \
  --log-group-name /ecs/dev-portal-pulumi-provisioner \
  --log-stream-name "$STREAM" \
  --query 'events[-20:].message' --output text \
  --region "$REGION" --profile "$PROFILE"
```

### Get Latest Portal Logs

```bash
STREAM=$(aws logs describe-log-streams \
  --log-group-name /portal/dev-portal \
  --order-by LastEventTime --descending --limit 1 \
  --query 'logStreams[0].logStreamName' --output text \
  --region "$REGION" --profile "$PROFILE")

aws logs get-log-events \
  --log-group-name /portal/dev-portal \
  --log-stream-name "$STREAM" \
  --query 'events[-20:].message' --output text \
  --region "$REGION" --profile "$PROFILE"
```

### Check ASG Status

```bash
aws autoscaling describe-instance-refreshes \
  --auto-scaling-group-name dev-portal-asg-* \
  --query 'InstanceRefreshes[0]' \
  --region "$REGION" --profile "$PROFILE"
```

### Check Target Group Health

```bash
aws elbv2 describe-target-health \
  --target-group-arn "arn:aws:elasticloadbalancing:us-east-2:878848911818:targetgroup/dev-portal-tg/..." \
  --region "$REGION" --profile "$PROFILE"
```

## Common Investigation Patterns

### NGFW Provisioning Issues
1. Check provisioner logs: `/ecs/dev-portal-pulumi-provisioner`
2. Look for: Pulumi errors, SSH wait timeouts, configuration failures
3. NGFW typically takes 15-25 minutes to boot and become SSH-accessible

### Range Provisioning Issues
1. Check provisioner logs: `/ecs/dev-portal-pulumi-provisioner`
2. Look for: Pulumi errors, instance creation failures, network issues

### Portal App Crashes
1. Check portal logs: `/portal/dev-portal`
2. Look for: Import errors, database connection issues, startup failures

### ASG/Deployment Issues
1. Check portal logs for health check failures
2. Check target group health
3. Check ASG instance refresh status

## AWS Profiles

- **Dev**: `panw-shifter-dev-workstation`
- **Prod**: `panw-shifter-prod-workstation`
- **Region**: `us-east-2`
