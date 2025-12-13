# Provisioner Smoke Test

## Setup

```bash
# Dev
export ENV=dev AWS_PROFILE=panw-shifter-dev-workstation

# Prod
export ENV=prod AWS_PROFILE=dev-workstation-user
```

## CLI Checks (Claude)

```bash
# State machines exist
aws stepfunctions list-state-machines --profile $AWS_PROFILE --region us-east-2 \
  --query "stateMachines[?contains(name, '${ENV}-portal')].name" --output table

# Lambda functions exist
aws lambda list-functions --profile $AWS_PROFILE --region us-east-2 \
  --query "Functions[?contains(FunctionName, '${ENV}-portal')].FunctionName" --output table
```

## Range Lifecycle Test

### You: Launch range from Portal UI

Note the range_id: ___

### Claude: Verify resources

```bash
RANGE_ID=XXX

# Check EC2s
aws ec2 describe-instances --profile $AWS_PROFILE --region us-east-2 \
  --filters "Name=tag:range_id,Values=$RANGE_ID" \
  --query 'Reservations[].Instances[].[Tags[?Key==`Name`].Value|[0],State.Name,PrivateIpAddress]' --output table

# Check subnet
aws ec2 describe-subnets --profile $AWS_PROFILE --region us-east-2 \
  --filters "Name=tag:range_id,Values=$RANGE_ID" \
  --query 'Subnets[0].[SubnetId,CidrBlock]' --output text
```

### You: Teardown range from Portal UI

### Claude: Verify cleanup

```bash
# Should show terminated or empty
aws ec2 describe-instances --profile $AWS_PROFILE --region us-east-2 \
  --filters "Name=tag:range_id,Values=$RANGE_ID" "Name=instance-state-name,Values=running" \
  --query 'Reservations[].Instances[].InstanceId' --output text

# Should be empty
aws ec2 describe-subnets --profile $AWS_PROFILE --region us-east-2 \
  --filters "Name=tag:range_id,Values=$RANGE_ID" \
  --query 'Subnets[].SubnetId' --output text
```
