---
name: aws-terraform
description: AWS CLI and Terraform commands for Shifter infrastructure. Use when running AWS commands, Terraform operations, or debugging infrastructure issues.
---

# AWS & Terraform Operations

Reference for AWS CLI and Terraform commands in the Shifter platform.

## AWS Profiles

Always specify an AWS profile when running commands:

| Environment | Profile Name                    | Usage                           |
|-------------|--------------------------------|----------------------------------|
| Dev         | `panw-shifter-dev-workstation` | Development/testing              |
| Prod        | `panw-shifter-prod-workstation`| Production (use with caution)    |

**Region**: `us-east-2` (all resources)

## AWS CLI Usage

### With Environment Variable
```bash
AWS_PROFILE=panw-shifter-dev-workstation AWS_REGION=us-east-2 aws <command>
```

### With Flag
```bash
aws --profile panw-shifter-dev-workstation --region us-east-2 <command>
```

## Common AWS Commands

### EC2 Instances
```bash
# List running instances
aws ec2 describe-instances \
  --profile panw-shifter-dev-workstation \
  --region us-east-2 \
  --filters "Name=instance-state-name,Values=running" \
  --query 'Reservations[].Instances[].[InstanceId,Tags[?Key==`Name`].Value|[0],PrivateIpAddress]' \
  --output table
```

### ECS Tasks
```bash
# List running tasks
aws ecs list-tasks \
  --profile panw-shifter-dev-workstation \
  --region us-east-2 \
  --cluster dev-portal
```

### Secrets Manager
```bash
# List secrets
aws secretsmanager list-secrets \
  --profile panw-shifter-dev-workstation \
  --region us-east-2

# Get secret value
aws secretsmanager get-secret-value \
  --profile panw-shifter-dev-workstation \
  --region us-east-2 \
  --secret-id <secret-id>
```

### CloudWatch Logs
```bash
# Tail logs
aws logs tail /ecs/dev-portal-pulumi-provisioner \
  --profile panw-shifter-dev-workstation \
  --region us-east-2 \
  --follow
```

## Terraform Usage

Terraform uses AWS credentials from the environment or provider config.

### Set Profile for Terraform
```bash
export AWS_PROFILE=panw-shifter-dev-workstation
export AWS_REGION=us-east-2
terraform plan
```

### Terraform Directories
- `platform/terraform/environments/dev/` - Dev environment configs
- `platform/terraform/environments/prod/` - Prod environment configs
- `platform/terraform/modules/` - Shared modules

### Common Terraform Commands
```bash
cd platform/terraform/environments/dev/portal

# Plan changes
terraform plan

# Apply changes
terraform apply

# Show state
terraform state list
terraform state show <resource>
```

## Important Notes

- **Always use profiles** - Never rely on default credentials
- **Dev first** - Test changes in dev before prod
- **Region is always us-east-2** - All Shifter resources are in this region
