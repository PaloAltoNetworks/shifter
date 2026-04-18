#!/bin/bash
# Rapidly test invoke_shell strategies against live NGFW

set -e

PROFILE="${AWS_PROFILE:-panw-shifter-dev-workstation}"
REGION="us-east-2"
PORTAL_ID="i-0e3a1f17656fa3162"
NGFW_IP="10.1.7.240"
SECRET_ARN="arn:aws:secretsmanager:us-east-2:878848911818:secret:shifter/dev/ngfw/79248efb-8f53-4fbc-af4b-be03df7f5883/ssh-key-8RoOlq"
STRATEGY="${1:-idle_timeout}"

echo "=== Rapid Invoke Shell Test ==="
echo "Strategy: $STRATEGY"
echo "NGFW: $NGFW_IP"
echo ""

# Get key
KEY_CONTENT=$(aws secretsmanager get-secret-value \
  --profile "$PROFILE" \
  --secret-id "$SECRET_ARN" \
  --region "$REGION" \
  --query 'SecretString' \
  --output text)

# Base64 encode to avoid quoting hell
KEY_B64=$(echo "$KEY_CONTENT" | base64 -w0)

# Python script inline
PYTHON_SCRIPT='
import sys, time, paramiko, io, re, base64

strategy = sys.argv[1]
key_b64 = sys.argv[2]
ngfw_ip = sys.argv[3]

key_content = base64.b64decode(key_b64).decode("utf-8")
key_file = io.StringIO(key_content)
pkey = paramiko.Ed25519Key.from_private_key(file_obj=key_file)

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname=ngfw_ip, username="admin", pkey=pkey, timeout=30, allow_agent=False, look_for_keys=False)

channel = client.invoke_shell()
channel.settimeout(120)
channel.send("show system info\\n")
channel.send("exit\\n")
channel.shutdown_write()

output = ""
start = time.time()
last_data = time.time()
chunks = 0

print(f"Testing: {strategy}", file=sys.stderr)

if strategy == "wait_for_exit":
    while True:
        if channel.recv_ready():
            chunk = channel.recv(4096).decode("utf-8", errors="replace")
            chunks += 1
            output += chunk
            last_data = time.time()
            print(f"Chunk {chunks}: {len(chunk)}b", file=sys.stderr)
        if channel.exit_status_ready():
            while channel.recv_ready():
                chunk = channel.recv(4096).decode("utf-8", errors="replace")
                chunks += 1
                output += chunk
            break
        if time.time() - start > 120:
            print("TIMEOUT", file=sys.stderr)
            break
        time.sleep(0.1)

elif strategy == "idle_timeout":
    while True:
        if channel.recv_ready():
            chunk = channel.recv(4096).decode("utf-8", errors="replace")
            chunks += 1
            output += chunk
            last_data = time.time()
            print(f"Chunk {chunks}: {len(chunk)}b", file=sys.stderr)
        idle = time.time() - last_data
        if idle > 3.0:
            print(f"Idle {idle:.1f}s - done", file=sys.stderr)
            break
        if channel.exit_status_ready():
            while channel.recv_ready():
                chunk = channel.recv(4096).decode("utf-8", errors="replace")
                chunks += 1
                output += chunk
            break
        if time.time() - start > 120:
            print("TIMEOUT", file=sys.stderr)
            break
        time.sleep(0.1)

elif strategy == "prompt_detect":
    while True:
        if channel.recv_ready():
            chunk = channel.recv(4096).decode("utf-8", errors="replace")
            chunks += 1
            output += chunk
            last_data = time.time()
            print(f"Chunk {chunks}: {len(chunk)}b", file=sys.stderr)
            if "admin@" in output[-200:] and ">" in output[-50:]:
                print("Prompt detected", file=sys.stderr)
                time.sleep(0.5)
                while channel.recv_ready():
                    chunk = channel.recv(4096).decode("utf-8", errors="replace")
                    chunks += 1
                    output += chunk
                break
        if channel.exit_status_ready():
            while channel.recv_ready():
                chunk = channel.recv(4096).decode("utf-8", errors="replace")
                chunks += 1
                output += chunk
            break
        if time.time() - start > 120:
            print("TIMEOUT", file=sys.stderr)
            break
        time.sleep(0.1)

elapsed = time.time() - start
exit_code = channel.recv_exit_status() if channel.exit_status_ready() else -1
client.close()

print(f"\\nTime: {elapsed:.1f}s", file=sys.stderr)
print(f"Chunks: {chunks}", file=sys.stderr)
print(f"Bytes: {len(output)}", file=sys.stderr)
print(f"Exit: {exit_code}", file=sys.stderr)

match = re.search(r"serial:\s*(\S+)", output, re.IGNORECASE)
if match:
    print(f"✓ Serial: {match.group(1)}", file=sys.stderr)
else:
    print("✗ No serial", file=sys.stderr)

print("\\n--- First 500 chars ---")
print(output[:500])
print("\\n--- Last 500 chars ---")
print(output[-500:])
'

# Run via SSM
TMPFILE=$(mktemp)
cat > "$TMPFILE" << EOF
{
  "commands": ["python3 -c $(echo "$PYTHON_SCRIPT" | jq -Rs .) $STRATEGY $KEY_B64 $NGFW_IP"]
}
EOF

CMD_ID=$(aws ssm send-command \
  --profile "$PROFILE" \
  --region "$REGION" \
  --instance-ids "$PORTAL_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters "file://$TMPFILE" \
  --timeout-seconds 300 \
  --query 'Command.CommandId' \
  --output text)

rm -f "$TMPFILE"

echo "Command ID: $CMD_ID"
echo "Waiting..."

for i in {1..60}; do
  sleep 2
  STATUS=$(aws ssm get-command-invocation --profile "$PROFILE" --region "$REGION" --command-id "$CMD_ID" --instance-id "$PORTAL_ID" --query 'Status' --output text 2>&1)
  if [ "$STATUS" != "Pending" ] && [ "$STATUS" != "InProgress" ]; then break; fi
done

echo ""
echo "=== STDERR (progress) ==="
aws ssm get-command-invocation --profile "$PROFILE" --region "$REGION" --command-id "$CMD_ID" --instance-id "$PORTAL_ID" --query 'StandardErrorContent' --output text

echo ""
echo "=== STDOUT (output sample) ==="
aws ssm get-command-invocation --profile "$PROFILE" --region "$REGION" --command-id "$CMD_ID" --instance-id "$PORTAL_ID" --query 'StandardOutputContent' --output text
