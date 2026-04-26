#!/usr/bin/env python3
"""Test SSH executor invoke_shell behavior against live NGFW."""

import sys
import time
import boto3
import paramiko

def get_ssh_key():
    """Get SSH key from Secrets Manager."""
    secret_arn = "arn:aws:secretsmanager:us-east-2:878848911818:secret:shifter/dev/ngfw/79248efb-8f53-4fbc-af4b-be03df7f5883/ssh-key-8RoOlq"

    session = boto3.Session(profile_name='panw-shifter-dev-workstation', region_name='us-east-2')
    client = session.client('secretsmanager')
    response = client.get_secret_value(SecretId=secret_arn)
    return response['SecretString']

def test_invoke_shell(strategy='wait_for_exit'):
    """Test different strategies for reading from invoke_shell."""

    print(f"\n{'='*70}")
    print(f"Testing strategy: {strategy}")
    print('='*70)

    # Get key
    print("Getting SSH key...")
    key_content = get_ssh_key()

    # Parse key
    import io
    key_file = io.StringIO(key_content)
    pkey = paramiko.Ed25519Key.from_private_key(file_obj=key_file)

    # Connect directly (assumes running on self-hosted runner with VPC access)
    print("Connecting to NGFW...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname='10.1.7.240',  # NGFW IP
        username='admin',
        pkey=pkey,
        timeout=30,
    )

    print("Opening interactive shell...")
    channel = client.invoke_shell()
    channel.settimeout(120)  # 2 minute timeout

    command = "show system info"
    print(f"Sending command: {command}")
    channel.send(command + "\n")
    channel.send("exit\n")
    channel.shutdown_write()

    # Different strategies
    output = ""
    start_time = time.time()
    chunk_count = 0
    last_data_time = time.time()

    if strategy == 'wait_for_exit':
        print("Strategy: Wait for channel exit")
        while True:
            if channel.recv_ready():
                chunk = channel.recv(4096).decode("utf-8", errors="replace")
                chunk_count += 1
                output += chunk
                last_data_time = time.time()
                print(f"  Chunk {chunk_count}: {len(chunk)} bytes")

            if channel.exit_status_ready():
                # Read any remaining data
                while channel.recv_ready():
                    chunk = channel.recv(4096).decode("utf-8", errors="replace")
                    chunk_count += 1
                    output += chunk
                    print(f"  Final chunk {chunk_count}: {len(chunk)} bytes")
                break

            elapsed = time.time() - start_time
            if elapsed > 120:
                print(f"  TIMEOUT after {elapsed:.1f}s")
                break

            time.sleep(0.1)

    elif strategy == 'idle_timeout':
        print("Strategy: Consider done after 3s idle")
        idle_threshold = 3.0

        while True:
            if channel.recv_ready():
                chunk = channel.recv(4096).decode("utf-8", errors="replace")
                chunk_count += 1
                output += chunk
                last_data_time = time.time()
                print(f"  Chunk {chunk_count}: {len(chunk)} bytes")

            # Check if we've been idle
            idle_time = time.time() - last_data_time
            if idle_time > idle_threshold:
                print(f"  Idle for {idle_time:.1f}s - considering complete")
                break

            # Also check exit status
            if channel.exit_status_ready():
                print(f"  Channel exit ready")
                while channel.recv_ready():
                    chunk = channel.recv(4096).decode("utf-8", errors="replace")
                    chunk_count += 1
                    output += chunk
                    print(f"  Final chunk {chunk_count}: {len(chunk)} bytes")
                break

            elapsed = time.time() - start_time
            if elapsed > 120:
                print(f"  TIMEOUT after {elapsed:.1f}s")
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
                print(f"  Chunk {chunk_count}: {len(chunk)} bytes")

                # Check if we see a prompt
                if output.strip().endswith('>') or 'admin@ngfw' in output[-100:]:
                    print(f"  Detected prompt - command complete")
                    time.sleep(0.5)  # Wait for any trailing data
                    while channel.recv_ready():
                        chunk = channel.recv(4096).decode("utf-8", errors="replace")
                        chunk_count += 1
                        output += chunk
                    break

            if channel.exit_status_ready():
                print(f"  Channel exit ready")
                while channel.recv_ready():
                    chunk = channel.recv(4096).decode("utf-8", errors="replace")
                    chunk_count += 1
                    output += chunk
                break

            elapsed = time.time() - start_time
            if elapsed > 120:
                print(f"  TIMEOUT after {elapsed:.1f}s")
                break

            time.sleep(0.1)

    elapsed = time.time() - start_time
    exit_code = channel.recv_exit_status() if channel.exit_status_ready() else -1

    print(f"\nCompleted in {elapsed:.1f}s")
    print(f"Exit code: {exit_code}")
    print(f"Received {len(output)} bytes in {chunk_count} chunks")
    print(f"\nFirst 500 chars:\n{output[:500]}")
    print(f"\nLast 500 chars:\n{output[-500:]}")

    # Check for serial
    if 'serial:' in output:
        import re
        match = re.search(r'serial:\s*(\S+)', output, re.IGNORECASE)
        if match:
            print(f"\n✓ Serial found: {match.group(1)}")
        else:
            print("\n✗ Serial line found but couldn't parse")
    else:
        print("\n✗ No serial found in output")

    client.close()
    return output

if __name__ == '__main__':
    strategy = sys.argv[1] if len(sys.argv) > 1 else 'wait_for_exit'
    test_invoke_shell(strategy)
