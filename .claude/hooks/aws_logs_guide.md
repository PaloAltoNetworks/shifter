# AWS Logs Reference Guide

## Log Groups by Component

### Portal/Platform Application
- **Log Group**: `/portal/dev-portal` (dev) / `/portal/prod-portal` (prod)
- **Use for**: Django app errors, startup issues, worker logs
- **Stream format**: Container ID hash

### Pulumi Provisioner (Range/NGFW)
- **Log Group**: `/ecs/dev-portal-pulumi-provisioner`
- **Use for**: Range provisioning, NGFW provisioning, Pulumi stack operations
- **Stream format**: `pulumi/pulumi-provisioner/<task-id>`
- **Find latest**: `aws logs describe-log-streams --log-group-name /ecs/dev-portal-pulumi-provisioner --order-by LastEventTime --descending --limit 1`

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

## Common Investigation Patterns

### NGFW Provisioning Issues
1. Check provisioner logs: `/ecs/dev-portal-pulumi-provisioner`
2. Look for: Pulumi errors, SSH wait timeouts, configuration failures
3. NGFW typically takes 5-10 minutes to boot and become SSH-accessible

### Range Provisioning Issues
1. Check provisioner logs: `/ecs/dev-portal-pulumi-provisioner`
2. Look for: Pulumi errors, instance creation failures, network issues

### Portal App Crashes
1. Check portal logs: `/portal/dev-portal`
2. Look for: Import errors, database connection issues, startup failures

### ASG/Deployment Issues
1. Check portal logs for health check failures
2. Check target group health: `aws elbv2 describe-target-health`
3. Check ASG instance refresh: `aws autoscaling describe-instance-refreshes`

## Quick Commands

```bash
# Get latest provisioner task logs
STREAM=$(aws logs describe-log-streams --log-group-name /ecs/dev-portal-pulumi-provisioner --order-by LastEventTime --descending --limit 1 --query 'logStreams[0].logStreamName' --output text --region us-east-2 --profile panw-shifter-dev-workstation)
aws logs get-log-events --log-group-name /ecs/dev-portal-pulumi-provisioner --log-stream-name "$STREAM" --query 'events[-20:].message' --output text --region us-east-2 --profile panw-shifter-dev-workstation

# Get latest portal logs
STREAM=$(aws logs describe-log-streams --log-group-name /portal/dev-portal --order-by LastEventTime --descending --limit 1 --query 'logStreams[0].logStreamName' --output text --region us-east-2 --profile panw-shifter-dev-workstation)
aws logs get-log-events --log-group-name /portal/dev-portal --log-stream-name "$STREAM" --query 'events[-20:].message' --output text --region us-east-2 --profile panw-shifter-dev-workstation

# Check ASG status
aws autoscaling describe-instance-refreshes --auto-scaling-group-name dev-portal-asg-2025122904363770930000000e --query 'InstanceRefreshes[0]' --region us-east-2 --profile panw-shifter-dev-workstation

# Check target group health
aws elbv2 describe-target-health --target-group-arn "arn:aws:elasticloadbalancing:us-east-2:878848911818:targetgroup/dev-portal-tg/cae78613aa247cb3" --region us-east-2 --profile panw-shifter-dev-workstation
```

## AWS Profiles
- **Dev**: `panw-shifter-dev-workstation`
- **Prod**: `panw-shifter-prod-workstation`
- **Region**: `us-east-2`
