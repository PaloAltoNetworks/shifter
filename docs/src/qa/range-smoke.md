# Range Smoke Test

Verify the Range VPC infrastructure is correctly deployed.

## Prerequisites

- Range terraform applied
- AWS CLI configured with appropriate profile

## Environment Setup

```bash
export ENV=dev  # or prod
export AWS_PROFILE=panw-shifter-${ENV}-workstation
export AWS_REGION=us-east-2
```

## Checks

### 1. VPC Exists

```bash
VPC_ID=$(aws ec2 describe-vpcs \
  --filters "Name=tag:Name,Values=${ENV}-range-vpc" \
  --query 'Vpcs[0].VpcId' --output text)

[ "$VPC_ID" != "None" ] && echo "PASS: VPC exists ($VPC_ID)" || echo "FAIL: VPC not found"
```

### 2. VPC Tags

```bash
aws ec2 describe-vpcs --vpc-ids "$VPC_ID" \
  --query 'Vpcs[0].Tags[?Key==`Environment`].Value' --output text | grep -q "$ENV" \
  && echo "PASS: Environment tag correct" || echo "FAIL: Environment tag missing/wrong"
```

### 3. Internet Gateway Attached

```bash
IGW=$(aws ec2 describe-internet-gateways \
  --filters "Name=attachment.vpc-id,Values=$VPC_ID" \
  --query 'InternetGateways[0].InternetGatewayId' --output text)

[ "$IGW" != "None" ] && echo "PASS: IGW attached ($IGW)" || echo "FAIL: No IGW attached"
```

### 4. Route Table Has Internet Route

```bash
RTB=$(aws ec2 describe-route-tables \
  --filters "Name=vpc-id,Values=$VPC_ID" "Name=tag:Name,Values=*public*" \
  --query 'RouteTables[0].RouteTableId' --output text)

aws ec2 describe-route-tables --route-table-ids "$RTB" \
  --query 'RouteTables[0].Routes[?DestinationCidrBlock==`0.0.0.0/0`].GatewayId' --output text | grep -q "igw-" \
  && echo "PASS: Internet route exists" || echo "FAIL: No internet route"
```

### 5. Victim Security Group

```bash
VICTIM_SG=$(aws ec2 describe-security-groups \
  --filters "Name=vpc-id,Values=$VPC_ID" "Name=tag:Name,Values=*victim*" \
  --query 'SecurityGroups[0].GroupId' --output text)

[ "$VICTIM_SG" != "None" ] && echo "PASS: Victim SG exists ($VICTIM_SG)" || echo "FAIL: Victim SG not found"
```

### 6. Kali Security Group

```bash
KALI_SG=$(aws ec2 describe-security-groups \
  --filters "Name=vpc-id,Values=$VPC_ID" "Name=tag:Name,Values=*kali*" \
  --query 'SecurityGroups[0].GroupId' --output text)

[ "$KALI_SG" != "None" ] && echo "PASS: Kali SG exists ($KALI_SG)" || echo "FAIL: Kali SG not found"
```

## Quick Run

```bash
#!/bin/bash
set -e
ENV=${1:-dev}
export AWS_PROFILE=panw-shifter-${ENV}-workstation
export AWS_REGION=us-east-2

echo "Range Smoke Test - $ENV"
echo "========================"

VPC_ID=$(aws ec2 describe-vpcs --filters "Name=tag:Name,Values=${ENV}-range-vpc" --query 'Vpcs[0].VpcId' --output text)
[ "$VPC_ID" == "None" ] && { echo "FAIL: VPC not found"; exit 1; }
echo "1. VPC exists: PASS ($VPC_ID)"

IGW=$(aws ec2 describe-internet-gateways --filters "Name=attachment.vpc-id,Values=$VPC_ID" --query 'InternetGateways[0].InternetGatewayId' --output text)
[ "$IGW" == "None" ] && { echo "FAIL: IGW not attached"; exit 1; }
echo "2. IGW attached: PASS ($IGW)"

VICTIM_SG=$(aws ec2 describe-security-groups --filters "Name=vpc-id,Values=$VPC_ID" "Name=tag:Name,Values=*victim*" --query 'SecurityGroups[0].GroupId' --output text)
[ "$VICTIM_SG" == "None" ] && { echo "FAIL: Victim SG not found"; exit 1; }
echo "3. Victim SG: PASS ($VICTIM_SG)"

KALI_SG=$(aws ec2 describe-security-groups --filters "Name=vpc-id,Values=$VPC_ID" "Name=tag:Name,Values=*kali*" --query 'SecurityGroups[0].GroupId' --output text)
[ "$KALI_SG" == "None" ] && { echo "FAIL: Kali SG not found"; exit 1; }
echo "4. Kali SG: PASS ($KALI_SG)"

echo "========================"
echo "All checks passed"
```

