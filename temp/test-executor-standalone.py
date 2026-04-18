#!/usr/bin/env python3
"""Standalone test of SSH executor invoke_shell strategies.

Designed to run ON the portal instance where it can reach NGFW directly.
Copy this file to portal and run: python3 test-executor-standalone.py [strategy]
"""

import sys
import time
import paramiko
import io
import re
import base64

# NGFW connection details
NGFW_IP = "10.1.7.240"

# SSH key (base64 encoded) - will be passed as arg
KEY_B64 = sys.argv[2] if len(sys.argv) > 2 else ""

def test_strategy(strategy):
    """Test invoke_shell with the given completion strategy."""

    print("=" * 70)
    print(f"Testing: {strategy}")
    print("=" * 70)

    # Decode key
    key_content = base64.b64decode(KEY_B64).decode("utf-8")
    key_file = io.StringIO(key_content)
    pkey = paramiko.Ed25519Key.from_private_key(file_obj=key_file)

    # Connect
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=NGFW_IP,
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
        while True:
            if channel.recv_ready():
                chunk = channel.recv(4096).decode("utf-8", errors="replace")
                chunk_count += 1
                output += chunk
                last_data_time = time.time()
                print(f"Chunk {chunk_count}: {len(chunk)}b", file=sys.stderr)

            if channel.exit_status_ready():
                while channel.recv_ready():
                    chunk = channel.recv(4096).decode("utf-8", errors="replace")
                    chunk_count += 1
                    output += chunk
                break

            if time.time() - start_time > 120:
                print("TIMEOUT", file=sys.stderr)
                break

            time.sleep(0.1)

    elif strategy == 'idle_timeout':
        idle_threshold = 3.0
        while True:
            if channel.recv_ready():
                chunk = channel.recv(4096).decode("utf-8", errors="replace")
                chunk_count += 1
                output += chunk
                last_data_time = time.time()
                print(f"Chunk {chunk_count}: {len(chunk)}b", file=sys.stderr)

            idle = time.time() - last_data_time
            if idle > idle_threshold:
                print(f"Idle {idle:.1f}s", file=sys.stderr)
                break

            if channel.exit_status_ready():
                while channel.recv_ready():
                    chunk = channel.recv(4096).decode("utf-8", errors="replace")
                    chunk_count += 1
                    output += chunk
                break

            if time.time() - start_time > 120:
                print("TIMEOUT", file=sys.stderr)
                break

            time.sleep(0.1)

    elif strategy == 'prompt_detect':
        while True:
            if channel.recv_ready():
                chunk = channel.recv(4096).decode("utf-8", errors="replace")
                chunk_count += 1
                output += chunk
                last_data_time = time.time()
                print(f"Chunk {chunk_count}: {len(chunk)}b", file=sys.stderr)

                if "admin@" in output[-200:] and ">" in output[-50:]:
                    print("Prompt detected", file=sys.stderr)
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

            if time.time() - start_time > 120:
                print("TIMEOUT", file=sys.stderr)
                break

            time.sleep(0.1)

    elapsed = time.time() - start_time
    exit_code = channel.recv_exit_status() if channel.exit_status_ready() else -1
    client.close()

    # Results
    print(f"Time: {elapsed:.1f}s", file=sys.stderr)
    print(f"Chunks: {chunk_count}", file=sys.stderr)
    print(f"Bytes: {len(output)}", file=sys.stderr)
    print(f"Exit: {exit_code}", file=sys.stderr)

    match = re.search(r"serial:\s*(\S+)", output, re.IGNORECASE)
    if match:
        print(f"✓ Serial: {match.group(1)}", file=sys.stderr)
    else:
        print("✗ No serial", file=sys.stderr)

    print("\n--- First 500 ---")
    print(output[:500])
    print("\n--- Last 500 ---")
    print(output[-500:])

if __name__ == '__main__':
    strategy = sys.argv[1] if len(sys.argv) > 1 else 'idle_timeout'
    test_strategy(strategy)
