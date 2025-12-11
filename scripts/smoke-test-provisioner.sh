#!/bin/bash
# Smoke Test for Shifter Provisioner Infrastructure
# Run with: AWS_PROFILE=dev-workstation-user ./scripts/smoke-test-provisioner.sh
#
# Prerequisites:
# - AWS CLI configured with dev-workstation-user profile
# - jq installed
# - Provisioner infrastructure deployed

set -e

REGION="us-east-2"
NAME_PREFIX="shifter"
PROFILE="${AWS_PROFILE:-dev-workstation-user}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

pass() { echo -e "${GREEN}✓ PASS${NC}: $1"; }
fail() { echo -e "${RED}✗ FAIL${NC}: $1"; exit 1; }
info() { echo -e "${YELLOW}→${NC} $1"; }
section() { echo -e "\n${YELLOW}━━━ $1 ━━━${NC}"; }

# ------------------------------------------------------------------------------
section "1. Lambda Functions"
# ------------------------------------------------------------------------------

LAMBDA_FUNCTIONS=(
    "${NAME_PREFIX}-create-subnet"
    "${NAME_PREFIX}-create-victim"
    "${NAME_PREFIX}-create-kali"
    "${NAME_PREFIX}-configure-librechat"
    "${NAME_PREFIX}-cleanup"
    "${NAME_PREFIX}-find-stale-ranges"
)

for fn in "${LAMBDA_FUNCTIONS[@]}"; do
    info "Checking Lambda function: $fn"

    # Check function exists and is active
    STATE=$(aws lambda get-function \
        --function-name "$fn" \
        --region "$REGION" \
        --profile "$PROFILE" \
        --query 'Configuration.State' \
        --output text 2>/dev/null) || fail "Lambda $fn not found"

    if [ "$STATE" == "Active" ]; then
        pass "Lambda $fn exists and is Active"
    else
        fail "Lambda $fn state is $STATE (expected Active)"
    fi
done

# Check Lambda layer exists
info "Checking Lambda shared layer"
LAYER_ARN=$(aws lambda list-layer-versions \
    --layer-name "${NAME_PREFIX}-provisioner-shared" \
    --region "$REGION" \
    --profile "$PROFILE" \
    --query 'LayerVersions[0].LayerVersionArn' \
    --output text 2>/dev/null) || fail "Lambda layer not found"

if [ "$LAYER_ARN" != "None" ] && [ -n "$LAYER_ARN" ]; then
    pass "Lambda shared layer exists: $LAYER_ARN"
else
    fail "Lambda shared layer not found"
fi

# ------------------------------------------------------------------------------
section "2. Step Functions State Machines"
# ------------------------------------------------------------------------------

STATE_MACHINES=(
    "${NAME_PREFIX}-provision-range"
    "${NAME_PREFIX}-teardown-range"
    "${NAME_PREFIX}-cleanup-stale-ranges"
)

for sm in "${STATE_MACHINES[@]}"; do
    info "Checking State Machine: $sm"

    SM_ARN=$(aws stepfunctions list-state-machines \
        --region "$REGION" \
        --profile "$PROFILE" \
        --query "stateMachines[?name=='$sm'].stateMachineArn" \
        --output text 2>/dev/null)

    if [ -n "$SM_ARN" ] && [ "$SM_ARN" != "None" ]; then
        # Check state machine status
        STATUS=$(aws stepfunctions describe-state-machine \
            --state-machine-arn "$SM_ARN" \
            --region "$REGION" \
            --profile "$PROFILE" \
            --query 'status' \
            --output text 2>/dev/null)

        if [ "$STATUS" == "ACTIVE" ]; then
            pass "State Machine $sm is ACTIVE"
        else
            fail "State Machine $sm status is $STATUS (expected ACTIVE)"
        fi
    else
        fail "State Machine $sm not found"
    fi
done

# ------------------------------------------------------------------------------
section "3. IAM Roles"
# ------------------------------------------------------------------------------

IAM_ROLES=(
    "${NAME_PREFIX}-provisioner-lambda"
    "${NAME_PREFIX}-provisioner-sfn"
    "${NAME_PREFIX}-provisioner-eventbridge"
)

for role in "${IAM_ROLES[@]}"; do
    info "Checking IAM Role: $role"

    ROLE_ARN=$(aws iam get-role \
        --role-name "$role" \
        --profile "$PROFILE" \
        --query 'Role.Arn' \
        --output text 2>/dev/null) || fail "IAM Role $role not found"

    if [ -n "$ROLE_ARN" ]; then
        pass "IAM Role $role exists"
    else
        fail "IAM Role $role not found"
    fi
done

# ------------------------------------------------------------------------------
section "4. Security Groups"
# ------------------------------------------------------------------------------

info "Checking Lambda Security Group"
SG_ID=$(aws ec2 describe-security-groups \
    --filters "Name=group-name,Values=${NAME_PREFIX}-provisioner-lambda" \
    --region "$REGION" \
    --profile "$PROFILE" \
    --query 'SecurityGroups[0].GroupId' \
    --output text 2>/dev/null)

if [ -n "$SG_ID" ] && [ "$SG_ID" != "None" ]; then
    pass "Lambda Security Group exists: $SG_ID"
else
    fail "Lambda Security Group not found"
fi

# ------------------------------------------------------------------------------
section "5. CloudWatch Log Groups"
# ------------------------------------------------------------------------------

LOG_GROUPS=(
    "/aws/lambda/${NAME_PREFIX}-create-subnet"
    "/aws/lambda/${NAME_PREFIX}-create-victim"
    "/aws/lambda/${NAME_PREFIX}-create-kali"
    "/aws/lambda/${NAME_PREFIX}-configure-librechat"
    "/aws/lambda/${NAME_PREFIX}-cleanup"
    "/aws/lambda/${NAME_PREFIX}-find-stale-ranges"
    "/aws/stepfunctions/${NAME_PREFIX}-provisioner"
)

for lg in "${LOG_GROUPS[@]}"; do
    info "Checking Log Group: $lg"

    # Log groups may not exist until first invocation, so we check if Lambda can create them
    EXISTS=$(aws logs describe-log-groups \
        --log-group-name-prefix "$lg" \
        --region "$REGION" \
        --profile "$PROFILE" \
        --query "logGroups[?logGroupName=='$lg'].logGroupName" \
        --output text 2>/dev/null)

    if [ -n "$EXISTS" ] && [ "$EXISTS" != "None" ]; then
        pass "Log Group $lg exists"
    else
        echo -e "${YELLOW}○ SKIP${NC}: Log Group $lg (will be created on first invocation)"
    fi
done

# ------------------------------------------------------------------------------
section "6. CloudWatch Alarms"
# ------------------------------------------------------------------------------

info "Checking CloudWatch Alarms"
ALARM_COUNT=$(aws cloudwatch describe-alarms \
    --alarm-name-prefix "$NAME_PREFIX" \
    --region "$REGION" \
    --profile "$PROFILE" \
    --query 'length(MetricAlarms)' \
    --output text 2>/dev/null)

if [ "$ALARM_COUNT" -gt 0 ]; then
    pass "Found $ALARM_COUNT CloudWatch alarms"

    # List alarm states
    aws cloudwatch describe-alarms \
        --alarm-name-prefix "$NAME_PREFIX" \
        --region "$REGION" \
        --profile "$PROFILE" \
        --query 'MetricAlarms[].{Name:AlarmName,State:StateValue}' \
        --output table
else
    echo -e "${YELLOW}○ SKIP${NC}: No alarms found (alarms may be disabled)"
fi

# ------------------------------------------------------------------------------
section "7. SNS Topics"
# ------------------------------------------------------------------------------

info "Checking SNS Alert Topic"
TOPIC_ARN=$(aws sns list-topics \
    --region "$REGION" \
    --profile "$PROFILE" \
    --query "Topics[?contains(TopicArn, '${NAME_PREFIX}-provisioner-alerts')].TopicArn" \
    --output text 2>/dev/null)

if [ -n "$TOPIC_ARN" ] && [ "$TOPIC_ARN" != "None" ]; then
    pass "SNS Alert Topic exists: $TOPIC_ARN"
else
    echo -e "${YELLOW}○ SKIP${NC}: SNS Topic not found (alarms may be disabled)"
fi

# ------------------------------------------------------------------------------
section "8. EventBridge Rules"
# ------------------------------------------------------------------------------

info "Checking EventBridge stale cleanup rule"
RULE_STATE=$(aws events describe-rule \
    --name "${NAME_PREFIX}-stale-range-cleanup" \
    --region "$REGION" \
    --profile "$PROFILE" \
    --query 'State' \
    --output text 2>/dev/null) || true

if [ "$RULE_STATE" == "ENABLED" ]; then
    pass "EventBridge stale cleanup rule is ENABLED"

    # Check targets
    TARGET_COUNT=$(aws events list-targets-by-rule \
        --rule "${NAME_PREFIX}-stale-range-cleanup" \
        --region "$REGION" \
        --profile "$PROFILE" \
        --query 'length(Targets)' \
        --output text 2>/dev/null)

    if [ "$TARGET_COUNT" -gt 0 ]; then
        pass "EventBridge rule has $TARGET_COUNT target(s)"
    else
        fail "EventBridge rule has no targets"
    fi
elif [ "$RULE_STATE" == "DISABLED" ]; then
    echo -e "${YELLOW}○ WARN${NC}: EventBridge rule exists but is DISABLED"
else
    fail "EventBridge stale cleanup rule not found"
fi

# ------------------------------------------------------------------------------
section "9. Database Connectivity (via Lambda)"
# ------------------------------------------------------------------------------

info "Testing find_stale_ranges Lambda (reads from DB)"
echo "Invoking Lambda to verify DB connectivity..."

INVOKE_RESULT=$(aws lambda invoke \
    --function-name "${NAME_PREFIX}-find-stale-ranges" \
    --region "$REGION" \
    --profile "$PROFILE" \
    --payload '{}' \
    --cli-binary-format raw-in-base64-out \
    /tmp/lambda-response.json 2>&1)

if [ $? -eq 0 ]; then
    RESPONSE=$(cat /tmp/lambda-response.json)

    # Check if response contains expected fields
    if echo "$RESPONSE" | jq -e '.stale_ranges' > /dev/null 2>&1; then
        STALE_COUNT=$(echo "$RESPONSE" | jq '.stale_ranges | length')
        pass "find_stale_ranges Lambda executed successfully (found $STALE_COUNT stale ranges)"
    elif echo "$RESPONSE" | jq -e '.errorMessage' > /dev/null 2>&1; then
        ERROR=$(echo "$RESPONSE" | jq -r '.errorMessage')
        fail "Lambda returned error: $ERROR"
    else
        echo -e "${YELLOW}○ WARN${NC}: Unexpected response format: $RESPONSE"
    fi
else
    fail "Failed to invoke Lambda: $INVOKE_RESULT"
fi

rm -f /tmp/lambda-response.json

# ------------------------------------------------------------------------------
section "10. Step Functions - Dry Run (Optional)"
# ------------------------------------------------------------------------------

info "Checking Step Functions execution history"

# Get provision state machine ARN
PROVISION_SM_ARN=$(aws stepfunctions list-state-machines \
    --region "$REGION" \
    --profile "$PROFILE" \
    --query "stateMachines[?name=='${NAME_PREFIX}-provision-range'].stateMachineArn" \
    --output text 2>/dev/null)

if [ -n "$PROVISION_SM_ARN" ] && [ "$PROVISION_SM_ARN" != "None" ]; then
    # List recent executions (if any)
    EXEC_COUNT=$(aws stepfunctions list-executions \
        --state-machine-arn "$PROVISION_SM_ARN" \
        --max-results 5 \
        --region "$REGION" \
        --profile "$PROFILE" \
        --query 'length(executions)' \
        --output text 2>/dev/null)

    if [ "$EXEC_COUNT" -gt 0 ]; then
        info "Recent provision executions:"
        aws stepfunctions list-executions \
            --state-machine-arn "$PROVISION_SM_ARN" \
            --max-results 5 \
            --region "$REGION" \
            --profile "$PROFILE" \
            --query 'executions[].{Name:name,Status:status,Started:startDate}' \
            --output table
    else
        info "No previous executions found (expected for new deployment)"
    fi

    pass "Step Functions state machine accessible"
fi

# ------------------------------------------------------------------------------
section "Summary"
# ------------------------------------------------------------------------------

echo -e "\n${GREEN}━━━ SMOKE TEST COMPLETE ━━━${NC}"
echo ""
echo "Infrastructure components verified:"
echo "  - 6 Lambda functions"
echo "  - 3 Step Functions state machines"
echo "  - 3 IAM roles"
echo "  - 1 Security group"
echo "  - CloudWatch log groups"
echo "  - CloudWatch alarms (if enabled)"
echo "  - SNS topics (if enabled)"
echo "  - EventBridge rules"
echo "  - Database connectivity"
echo ""
echo "Next steps for full integration test:"
echo "  1. Create a test range via Portal API"
echo "  2. Monitor Step Functions execution"
echo "  3. Verify range resources created in AWS"
echo "  4. Test teardown flow"
echo ""
