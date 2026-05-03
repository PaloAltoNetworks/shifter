#!/bin/bash
# Test different invoke_shell strategies via SSM on portal instance

set -e

PROFILE="${AWS_PROFILE:-panw-shifter-dev-workstation}"
REGION="us-east-2"
PORTAL_ID="i-0e3a1f17656fa3162"
NGFW_IP="10.1.7.240"
SECRET_ARN="arn:aws:secretsmanager:us-east-2:878848911818:secret:shifter/dev/ngfw/79248efb-8f53-4fbc-af4b-be03df7f5883/ssh-key-8RoOlq"

STRATEGY="${1:-idle_timeout}"

echo "Testing strategy: $STRATEGY"
echo "NGFW IP: $NGFW_IP"
echo ""

# Create Python test script
cat > /tmp/test-invoke.py << 'EOFPYTHON'
import sys
import time
import json
import paramiko
import io

def test_strategy(strategy, key_content, ngfw_ip):
    """Test invoke_shell with different completion strategies."""

    # Parse key
    key_file = io.StringIO(key_content)
    pkey = paramiko.Ed25519Key.from_private_key(file_obj=key_file)

    # Connect
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=ngfw_ip,
        username='admin',
        pkey=pkey,
        timeout=30,
        allow_agent=False,
        look_for_keys=False,
    )

    # Open shell
    channel = client.invoke_shell()
    channel.settimeout(120)

    # Send command
    channel.send("show system info\n")
    channel.send("exit\n")
    channel.shutdown_write()

    # Read with strategy
    output = ""
    start_time = time.time()
    last_data_time = time.time()
    chunk_count = 0

    if strategy == 'wait_for_exit':
        print("Strategy: Wait for channel.exit_status_ready()")
        while True:
            if channel.recv_ready():
                chunk = channel.recv(4096).decode("utf-8", errors="replace")
                chunk_count += 1
                output += chunk
                last_data_time = time.time()
                print(f"  Chunk {chunk_count}: {len(chunk)} bytes", file=sys.stderr)

            if channel.exit_status_ready():
                while channel.recv_ready():
                    chunk = channel.recv(4096).decode("utf-8", errors="replace")
                    chunk_count += 1
                    output += chunk
                break

            elapsed = time.time() - start_time
            if elapsed > 120:
                print(f"  TIMEOUT after {elapsed:.1f}s", file=sys.stderr)
                break

            time.sleep(0.1)

    elif strategy == 'idle_timeout':
        print("Strategy: Exit after 3s idle")
        idle_threshold = 3.0

        while True:
            if channel.recv_ready():
                chunk = channel.recv(4096).decode("utf-8", errors="replace")
                chunk_count += 1
                output += chunk
                last_data_time = time.time()
                print(f"  Chunk {chunk_count}: {len(chunk)} bytes", file=sys.stderr)

            idle_time = time.time() - last_data_time
            if idle_time > idle_threshold:
                print(f"  Idle for {idle_time:.1f}s - done", file=sys.stderr)
                break

            if channel.exit_status_ready():
                while channel.recv_ready():
                    chunk = channel.recv(4096).decode("utf-8", errors="replace")
                    chunk_count += 1
                    output += chunk
                break

            elapsed = time.time() - start_time
            if elapsed > 120:
                print(f"  TIMEOUT after {elapsed:.1f}s", file=sys.stderr)
                break

            time.sleep(0.1)

    elif strategy == 'prompt_detection':
        print("Strategy: Detect prompt pattern")

        while True:
            if channel.recv_ready():
                chunk = channel.recv(4096).decode("utf-8", errors="replace")
                chunk_count += 1
                output += chunk
                last_data_time = time.time()
                print(f"  Chunk {chunk_count}: {len(chunk)} bytes", file=sys.stderr)

                # Look for prompt in last 200 chars
                if 'admin@' in output[-200:] and '>' in output[-50:]:
                    print(f"  Detected prompt - done", file=sys.stderr)
                    time.sleep(0.5)
                    while channel.recv_ready():
                        chunk = channel.recv(4096).decode("utf-8", errors="replace")
                        chunk_count += 1
                        output += chunk
                    break

            if channel.exit_status_ready():
                while channel.recv_ready():
                    chunk = channel.recv(4096).decode("utf-8", errors="replace")
                    chunk_count += 1
                    output += chunk
                break

            elapsed = time.time() - start_time
            if elapsed > 120:
                print(f"  TIMEOUT after {elapsed:.1f}s", file=sys.stderr)
                break

            time.sleep(0.1)

    elapsed = time.time() - start_time
    exit_code = channel.recv_exit_status() if channel.exit_status_ready() else -1

    # Results
    print(f"\nCompleted in {elapsed:.1f}s", file=sys.stderr)
    print(f"Exit code: {exit_code}", file=sys.stderr)
    print(f"Received {len(output)} bytes in {chunk_count} chunks", file=sys.stderr)

    # Check for serial
    import re
    match = re.search(r'serial:\s*(\S+)', output, re.IGNORECASE)
    if match:
        print(f"✓ Serial found: {match.group(1)}", file=sys.stderr)
    else:
        print(f"✗ Serial NOT found", file=sys.stderr)

    client.close()

    # Return summary
    return {
        'strategy': strategy,
        'elapsed': elapsed,
        'chunks': chunk_count,
        'bytes': len(output),
        'exit_code': exit_code,
        'serial_found': bool(match),
        'serial': match.group(1) if match else None,
        'first_500': output[:500],
        'last_500': output[-500:],
    }

if __name__ == '__main__':
    strategy = sys.argv[1]
    key_content = sys.argv[2]
    ngfw_ip = sys.argv[3]

    result = test_strategy(strategy, key_content, ngfw_ip)
    print(json.dumps(result, indent=2))
EOFPYTHON

# Get SSH key
echo "Getting SSH key..."
KEY_CONTENT=$(aws secretsmanager get-secret-value \
  --profile "$PROFILE" \
  --secret-id "$SECRET_ARN" \
  --region "$REGION" \
  --query 'SecretString' \
  --output text 2>&1)

# Create SSM command parameters
TMPFILE=$(mktemp)
cat > "$TMPFILE" << EOF
{
  "commands": [
    "python3 << 'EOFSCRIPT'",
    $(cat /tmp/test-invoke.py | jq -Rs .),
    "EOFSCRIPT",
    "exit 0"
  ],
  "executionTimeout": ["300"]
}
EOF

echo "Sending test script to portal instance..."
CMD_ID=$(aws ssm send-command \
  --profile "$PROFILE" \
  --region "$REGION" \
  --instance-ids "$PORTAL_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters "{\"commands\":[\"python3 -c $(cat /tmp/test-invoke.py | jq -Rs .) $STRATEGY $(echo "$KEY_CONTENT" | jq -Rs .) $NGFW_IP\"]}" \
  --timeout-seconds 300 \
  --query 'Command.CommandId' \
  --output text 2>&1)

rm -f "$TMPFILE"

echo "Command ID: $CMD_ID"
echo "Waiting for results..."

# Poll for completion
for i in {1..60}; do
  sleep 2
  STATUS=$(aws ssm get-command-invocation \
    --profile "$PROFILE" \
    --region "$REGION" \
    --command-id "$CMD_ID" \
    --instance-id "$PORTAL_ID" \
    --query 'Status' \
    --output text 2>&1)

  if [ "$STATUS" != "Pending" ] && [ "$STATUS" != "InProgress" ]; then
    break
  fi
done

echo ""
echo "=== Results ==="
aws ssm get-command-invocation \
  --profile "$PROFILE" \
  --region "$REGION" \
  --command-id "$CMD_ID" \
  --instance-id "$PORTAL_ID" \
  --query '[Status,StandardOutputContent,StandardErrorContent]' \
  --output json 2>&1 | jq -r '.[1], "\n--- STDERR ---\n", .[2]'
