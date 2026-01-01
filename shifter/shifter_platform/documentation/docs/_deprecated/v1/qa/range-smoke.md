# Range Smoke Test

## Setup

```bash
# Dev
export ENV=dev AWS_PROFILE=panw-shifter-dev-workstation

# Prod
export ENV=prod AWS_PROFILE=dev-workstation-user
```

## CLI Checks (Claude)

```bash
# VPC exists
aws ec2 describe-vpcs --profile $AWS_PROFILE --region us-east-2 \
  --filters "Name=tag:Name,Values=${ENV}-range-vpc" \
  --query 'Vpcs[0].[VpcId,CidrBlock]' --output text

# IGW attached
aws ec2 describe-internet-gateways --profile $AWS_PROFILE --region us-east-2 \
  --filters "Name=tag:Name,Values=${ENV}-range-igw" \
  --query 'InternetGateways[0].InternetGatewayId' --output text

# Security groups
aws ec2 describe-security-groups --profile $AWS_PROFILE --region us-east-2 \
  --filters "Name=tag:Name,Values=${ENV}-range-*" \
  --query 'SecurityGroups[*].[GroupName,GroupId]' --output table
```
