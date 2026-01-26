---
name: aws-logs
description: Query AWS CloudWatch logs for Shifter components. Use when investigating provisioner issues, portal errors, range problems, or any AWS infrastructure debugging.
---

# AWS Logs Reference

Query CloudWatch logs for Shifter platform components.

## CRITICAL: How to Call AWS CLI

**DO NOT** use `--query` and `--output text` with variable assignment or piping. This pattern consistently fails.

**DO NOT** pipe AWS CLI output to `jq`. This also fails.

**CORRECT approach**: Make plain AWS CLI calls and let them return JSON. Execute commands in separate steps:

```bash
# Step 1: Get the stream name (returns JSON, read the logStreamName from output)
aws logs describe-log-streams \
  --log-group-name /ecs/dev-portal-pulumi-provisioner \
  --order-by LastEventTime --descending --limit 1 \
  --region us-east-2 --profile panw-shifter-dev-workstation

# Step 2: Use the stream name from the JSON output in a second call
aws logs get-log-events \
  --log-group-name /ecs/dev-portal-pulumi-provisioner \
  --log-stream-name "pulumi/pulumi-provisioner/<task-id-from-step-1>" \
  --limit 50 \
  --region us-east-2 --profile panw-shifter-dev-workstation
```

Make **two separate Bash tool calls** - one to get the stream name, then read the JSON and make a second call with the stream name.

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

**Remember: Make separate AWS CLI calls. Do NOT use --query/--output text with variable assignment.**

### Get Latest Provisioner Logs

```bash
# Call 1: Get stream name (read logStreamName from JSON output)
aws logs describe-log-streams \
  --log-group-name /ecs/dev-portal-pulumi-provisioner \
  --order-by LastEventTime --descending --limit 1 \
  --region us-east-2 --profile panw-shifter-dev-workstation

# Call 2: Get log events (use stream name from Call 1)
aws logs get-log-events \
  --log-group-name /ecs/dev-portal-pulumi-provisioner \
  --log-stream-name "pulumi/pulumi-provisioner/<TASK_ID>" \
  --limit 50 \
  --region us-east-2 --profile panw-shifter-dev-workstation
```

### Get Latest Portal Logs

```bash
# Call 1: Get stream name
aws logs describe-log-streams \
  --log-group-name /portal/dev-portal \
  --order-by LastEventTime --descending --limit 1 \
  --region us-east-2 --profile panw-shifter-dev-workstation

# Call 2: Get log events (use stream name from Call 1)
aws logs get-log-events \
  --log-group-name /portal/dev-portal \
  --log-stream-name "<STREAM_NAME>" \
  --limit 50 \
  --region us-east-2 --profile panw-shifter-dev-workstation
```

### Check ASG Status

```bash
aws autoscaling describe-instance-refreshes \
  --auto-scaling-group-name dev-portal-asg \
  --region us-east-2 --profile panw-shifter-dev-workstation
```

### Check Target Group Health

```bash
aws elbv2 describe-target-health \
  --target-group-arn "arn:aws:elasticloadbalancing:us-east-2:878848911818:targetgroup/dev-portal-tg/..." \
  --region us-east-2 --profile panw-shifter-dev-workstation
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
