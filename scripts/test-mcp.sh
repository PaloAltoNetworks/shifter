#!/usr/bin/env bash
#
# Test MCP server directly via SSM, bypassing OpenWebUI wrapper.
# Useful for debugging MCP issues independent of the UI layer.
#
# Prerequisites:
#   - AWS CLI configured with appropriate profile
#   - Active range in the target environment
#   - JWT token from browser dev tools (Network tab -> request headers)
#
# Usage:
#   ./scripts/test-mcp.sh <jwt_token>           # Test dev (default)
#   ./scripts/test-mcp.sh -e prod <jwt_token>   # Test prod
#
set -euo pipefail

# Defaults
ENV="dev"
AWS_REGION="${AWS_REGION:-us-east-2}"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -e|--env)
            ENV="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [-e|--env <dev|prod>] <jwt_token>"
            echo ""
            echo "Test MCP server directly via SSM."
            echo ""
            echo "To get a JWT token:"
            echo "  1. Open browser dev tools (F12)"
            echo "  2. Go to Network tab"
            echo "  3. Use the chat and look for /mcp requests"
            echo "  4. Copy the Authorization header value (without 'Bearer ')"
            exit 0
            ;;
        -*)
            echo "Unknown option: $1"
            echo "Usage: $0 [-e|--env <dev|prod>] <jwt_token>"
            exit 1
            ;;
        *)
            TOKEN="$1"
            shift
            ;;
    esac
done

# Validate token provided
if [[ -z "${TOKEN:-}" ]]; then
    echo "Error: JWT token required"
    echo "Usage: $0 [-e|--env <dev|prod>] <jwt_token>"
    exit 1
fi

# Validate environment
if [[ "$ENV" != "dev" && "$ENV" != "prod" ]]; then
    echo "Error: Environment must be 'dev' or 'prod'"
    exit 1
fi

# Set profile based on environment
if [[ "$ENV" == "dev" ]]; then
    AWS_PROFILE="$PANW_SHIFTER_DEV_PROFILE"
else
    AWS_PROFILE="$PANW_SHIFTER_PROD_PROFILE"
fi

INSTANCE_TAG="${ENV}-agentchat-ec2"

# Get the AgentChat EC2 instance ID
echo "Finding AgentChat EC2 instance for $ENV..."
INSTANCE_ID=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=$INSTANCE_TAG" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].InstanceId' \
  --output text \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE")

if [ "$INSTANCE_ID" == "None" ] || [ -z "$INSTANCE_ID" ]; then
  echo "Error: Could not find running AgentChat EC2 instance for $ENV"
  exit 1
fi

echo "Instance: $INSTANCE_ID"
echo ""

# Build the test script to run on EC2
# Uses heredoc to preserve the script with proper escaping
TEST_SCRIPT=$(cat << 'SCRIPT_EOF'
#!/bin/bash
set -e
TOKEN="__TOKEN__"
HOST="http://localhost:3001"

echo "=== MCP Server Test ==="
echo ""

# 1. Health check
echo "1. Health check..."
HEALTH=$(curl -sf "$HOST/health" 2>&1) || { echo "FAILED: $HEALTH"; exit 1; }
echo "$HEALTH" | jq .
echo ""

# 2. Initialize session
echo "2. Initialize MCP session..."
INIT_RESPONSE=$(curl -sf "$HOST/mcp" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "2024-11-05",
      "capabilities": {},
      "clientInfo": {"name": "test-client", "version": "1.0.0"}
    }
  }' 2>&1)

if echo "$INIT_RESPONSE" | jq -e '.error' > /dev/null 2>&1; then
    echo "FAILED:"
    echo "$INIT_RESPONSE" | jq .
    exit 1
fi
echo "$INIT_RESPONSE" | jq .
echo ""

# Get session ID from response header
SESSION_ID=$(curl -sI "$HOST/mcp" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "2024-11-05",
      "capabilities": {},
      "clientInfo": {"name": "test-client", "version": "1.0.0"}
    }
  }' 2>/dev/null | grep -i 'mcp-session-id' | awk '{print $2}' | tr -d '\r\n')

if [ -z "$SESSION_ID" ]; then
  echo "ERROR: No mcp-session-id header"
  exit 1
fi
echo "Session ID: $SESSION_ID"
echo ""

# 3. List tools
echo "3. List tools..."
TOOLS=$(curl -sf "$HOST/mcp" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "mcp-session-id: $SESSION_ID" \
  -d '{"jsonrpc": "2.0", "id": 2, "method": "tools/list"}' 2>&1)

if [ -z "$TOOLS" ]; then
    echo "FAILED: Empty response (possible SSE mode issue)"
    exit 1
fi
echo "$TOOLS" | jq .
echo ""

# 4. Test run_command if available
if echo "$TOOLS" | jq -e '.result.tools[] | select(.name=="run_command")' > /dev/null 2>&1; then
  echo "4. Test run_command (uptime)..."
  RESULT=$(curl -sf "$HOST/mcp" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -H "mcp-session-id: $SESSION_ID" \
    -d '{
      "jsonrpc": "2.0",
      "id": 3,
      "method": "tools/call",
      "params": {"name": "run_command", "arguments": {"command": "uptime"}}
    }' 2>&1)
  echo "$RESULT" | jq .
else
  echo "4. Skipping tool test (run_command not found)"
fi

echo ""
echo "=== Test Complete ==="
SCRIPT_EOF
)

# Replace token placeholder
TEST_SCRIPT="${TEST_SCRIPT//__TOKEN__/$TOKEN}"

echo "Running MCP tests on $INSTANCE_ID..."
echo ""

# Execute via SSM
COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters "commands=[\"$TEST_SCRIPT\"]" \
  --query 'Command.CommandId' \
  --output text \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE")

echo "SSM Command ID: $COMMAND_ID"
echo "Waiting for results..."
echo ""

# Poll for completion
# shellcheck disable=SC2034
for i in {1..30}; do
    sleep 2
    STATUS=$(aws ssm get-command-invocation \
      --command-id "$COMMAND_ID" \
      --instance-id "$INSTANCE_ID" \
      --query 'Status' \
      --output text \
      --region "$AWS_REGION" \
      --profile "$AWS_PROFILE" 2>/dev/null || echo "Pending")

    if [ "$STATUS" == "Success" ]; then
        aws ssm get-command-invocation \
          --command-id "$COMMAND_ID" \
          --instance-id "$INSTANCE_ID" \
          --query 'StandardOutputContent' \
          --output text \
          --region "$AWS_REGION" \
          --profile "$AWS_PROFILE"
        exit 0
    elif [ "$STATUS" == "Failed" ] || [ "$STATUS" == "Cancelled" ] || [ "$STATUS" == "TimedOut" ]; then
        echo "Command failed with status: $STATUS"
        echo ""
        echo "=== STDERR ==="
        aws ssm get-command-invocation \
          --command-id "$COMMAND_ID" \
          --instance-id "$INSTANCE_ID" \
          --query 'StandardErrorContent' \
          --output text \
          --region "$AWS_REGION" \
          --profile "$AWS_PROFILE"
        exit 1
    fi
done

echo "Timeout waiting for SSM command"
exit 1
