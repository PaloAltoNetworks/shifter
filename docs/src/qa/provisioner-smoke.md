# Provisioner Smoke Test

Verify the Step Functions provisioner can create and teardown ranges.

## Prerequisites

- Portal and Range infrastructure deployed
- At least one user account in Cognito
- AWS CLI configured with appropriate profile

## Environment Setup

```bash
export ENV=dev  # or prod
export AWS_PROFILE=panw-shifter-${ENV}-workstation
export AWS_REGION=us-east-2
```

## Checks

### 1. State Machines Exist

```bash
PROVISION_ARN=$(aws stepfunctions list-state-machines \
  --query "stateMachines[?contains(name, '${ENV}-portal-provision-range')].stateMachineArn | [0]" --output text)

[ "$PROVISION_ARN" != "None" ] && echo "PASS: Provision state machine exists" || echo "FAIL: Provision state machine not found"

TEARDOWN_ARN=$(aws stepfunctions list-state-machines \
  --query "stateMachines[?contains(name, '${ENV}-portal-teardown-range')].stateMachineArn | [0]" --output text)

[ "$TEARDOWN_ARN" != "None" ] && echo "PASS: Teardown state machine exists" || echo "FAIL: Teardown state machine not found"
```

### 2. Lambda Functions Exist

```bash
for FUNC in create-subnet create-victim create-kali update-range cleanup-range; do
  aws lambda get-function --function-name "${ENV}-portal-${FUNC}" > /dev/null 2>&1 \
    && echo "PASS: Lambda ${FUNC} exists" || echo "FAIL: Lambda ${FUNC} not found"
done
```

### 3. Provision a Test Range

Via Portal UI (preferred):
1. Login to portal
2. Click "Launch Range"
3. Wait for status to show "ready"

Or via CLI:

```bash
# Get a test range_id from the database or create via portal
RANGE_ID=1  # adjust as needed

# Execute provision state machine
EXECUTION_ARN=$(aws stepfunctions start-execution \
  --state-machine-arn "$PROVISION_ARN" \
  --input "{\"range_id\": $RANGE_ID}" \
  --query 'executionArn' --output text)

echo "Started execution: $EXECUTION_ARN"

# Wait for completion (up to 5 min)
aws stepfunctions describe-execution --execution-arn "$EXECUTION_ARN" \
  --query 'status' --output text
```

Expected: Status becomes `SUCCEEDED`.

### 4. Verify Resources Created

After provision completes:

```bash
# Check for user subnet
aws ec2 describe-subnets \
  --filters "Name=tag:range_id,Values=$RANGE_ID" \
  --query 'Subnets[0].SubnetId' --output text | grep -q "subnet-" \
  && echo "PASS: Subnet created" || echo "FAIL: Subnet not found"

# Check for victim EC2
aws ec2 describe-instances \
  --filters "Name=tag:range_id,Values=$RANGE_ID" "Name=tag:role,Values=victim" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text | grep -q "i-" \
  && echo "PASS: Victim EC2 created" || echo "FAIL: Victim EC2 not found"

# Check for Kali EC2
aws ec2 describe-instances \
  --filters "Name=tag:range_id,Values=$RANGE_ID" "Name=tag:role,Values=kali" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text | grep -q "i-" \
  && echo "PASS: Kali EC2 created" || echo "FAIL: Kali EC2 not found"
```

### 5. Teardown the Test Range

```bash
EXECUTION_ARN=$(aws stepfunctions start-execution \
  --state-machine-arn "$TEARDOWN_ARN" \
  --input "{\"range_id\": $RANGE_ID}" \
  --query 'executionArn' --output text)

echo "Started teardown: $EXECUTION_ARN"

# Wait for completion
aws stepfunctions describe-execution --execution-arn "$EXECUTION_ARN" \
  --query 'status' --output text
```

Expected: Status becomes `SUCCEEDED`.

### 6. Verify Resources Cleaned Up

```bash
# Subnet should be gone
aws ec2 describe-subnets \
  --filters "Name=tag:range_id,Values=$RANGE_ID" \
  --query 'Subnets[0].SubnetId' --output text | grep -q "None" \
  && echo "PASS: Subnet cleaned up" || echo "FAIL: Subnet still exists"

# Instances should be terminated or gone
aws ec2 describe-instances \
  --filters "Name=tag:range_id,Values=$RANGE_ID" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text | grep -q "None" \
  && echo "PASS: Instances cleaned up" || echo "FAIL: Instances still running"
```

### 7. Check CloudWatch Logs

```bash
# Recent errors in provision Lambda
aws logs filter-log-events \
  --log-group-name "/aws/lambda/${ENV}-portal-create-victim" \
  --filter-pattern "ERROR" \
  --start-time $(($(date +%s) - 3600))000 \
  --query 'events[*].message' --output text

# Should return empty if no errors
```

## Notes

- Provisioning takes 2-3 minutes typically
- Teardown takes 1-2 minutes
- If Step Function fails, check CloudWatch logs for the specific Lambda

