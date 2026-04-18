#!/usr/bin/env python3
"""Test SSH executor against NGFW via SSM tunnel through portal.

Tunnel must be running: localhost:2222 -> portal:22 (via SSM)
Portal can then reach NGFW at 10.1.7.240
"""

import sys
import os
import time
import boto3
import paramiko
import io

sys.path.insert(0, '/home/atomik/src/shifter/shifter/engine/provisioner')

def get_ssh_key():
    """Get NGFW SSH key from Secrets Manager."""
    secret_arn = "arn:aws:secretsmanager:us-east-2:878848911818:secret:shifter/dev/ngfw/79248efb-8f53-4fbc-af4b-be03df7f5883/ssh-key-8RoOlq"

    session = boto3.Session(profile_name='panw-shifter-dev-workstation', region_name='us-east-2')
    client = session.client('secretsmanager')
    response = client.get_secret_value(SecretId=secret_arn)
    return response['SecretString']

def test_invoke_shell_with_tunnel(strategy='idle_timeout'):
    """Test invoke_shell strategies using SSM tunnel through portal."""

    print("=" * 70)
    print(f"Testing invoke_shell with strategy: {strategy}")
    print("=" * 70)
    print()

    # Get NGFW key
    print("Getting NGFW SSH key...")
    ngfw_key_content = get_ssh_key()
    key_file = io.StringIO(ngfw_key_content)
    ngfw_pkey = paramiko.Ed25519Key.from_private_key(file_obj=key_file)

    # Connect to portal via tunnel
    print("Connecting to portal via SSM tunnel (localhost:2222)...")
    portal_client = paramiko.SSHClient()
    portal_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    portal_client.connect(
        hostname='localhost',
        port=2222,
        username='ec2-user',  # Portal uses ec2-user
        timeout=30,
    )

    # Get transport and open channel to NGFW through portal
    print("Opening channel to NGFW (10.1.7.240) through portal...")
    transport = portal_client.get_transport()
    dest_addr = ('10.1.7.240', 22)
    local_addr = ('127.0.0.1', 0)
    channel = transport.open_channel('direct-tcpip', dest_addr, local_addr)

    # Now connect SSH to NGFW using the channel
    print("Connecting to NGFW via channel...")
    ngfw_client = paramiko.SSHClient()
    ngfw_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    # Use the channel as the socket
    ngfw_client.connect(
        hostname='10.1.7.240',  # Not actually used, but required
        username='admin',
        pkey=ngfw_pkey,
        sock=channel,
        timeout=30,
        allow_agent=False,
        look_for_keys=False,
    )

    print("Opening interactive shell on NGFW...")
    shell_channel = ngfw_client.invoke_shell()
    shell_channel.settimeout(120)

    # Send command
    print("Sending: show system info")
    shell_channel.send("show system info\n")
    shell_channel.send("exit\n")
    shell_channel.shutdown_write()

    # Read with different strategies
    output = ""
    start_time = time.time()
    last_data_time = time.time()
    chunk_count = 0

    print(f"\nReading output with '{strategy}' strategy...")

    if strategy == 'wait_for_exit':
        print("  Waiting for channel.exit_status_ready()...")
        while True:
            if shell_channel.recv_ready():
                chunk = shell_channel.recv(4096).decode("utf-8", errors="replace")
                chunk_count += 1
                output += chunk
                last_data_time = time.time()
                print(f"  Chunk {chunk_count}: {len(chunk)} bytes")

            if shell_channel.exit_status_ready():
                while shell_channel.recv_ready():
                    chunk = shell_channel.recv(4096).decode("utf-8", errors="replace")
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
        idle_threshold = 3.0
        print(f"  Will exit after {idle_threshold}s idle...")

        while True:
            if shell_channel.recv_ready():
                chunk = shell_channel.recv(4096).decode("utf-8", errors="replace")
                chunk_count += 1
                output += chunk
                last_data_time = time.time()
                print(f"  Chunk {chunk_count}: {len(chunk)} bytes")

            idle_time = time.time() - last_data_time
            if idle_time > idle_threshold:
                print(f"  Idle for {idle_time:.1f}s - considering complete")
                break

            if shell_channel.exit_status_ready():
                while shell_channel.recv_ready():
                    chunk = shell_channel.recv(4096).decode("utf-8", errors="replace")
                    chunk_count += 1
                    output += chunk
                break

            elapsed = time.time() - start_time
            if elapsed > 120:
                print(f"  TIMEOUT after {elapsed:.1f}s")
                break

            time.sleep(0.1)

    elif strategy == 'prompt_detect':
        print("  Looking for prompt pattern...")

        while True:
            if shell_channel.recv_ready():
                chunk = shell_channel.recv(4096).decode("utf-8", errors="replace")
                chunk_count += 1
                output += chunk
                last_data_time = time.time()
                print(f"  Chunk {chunk_count}: {len(chunk)} bytes")

                # Check for prompt in recent output
                if "admin@" in output[-200:] and ">" in output[-50:]:
                    print(f"  Detected prompt - command complete")
                    time.sleep(0.5)  # Wait for any trailing data
                    while shell_channel.recv_ready():
                        chunk = shell_channel.recv(4096).decode("utf-8", errors="replace")
                        chunk_count += 1
                        output += chunk
                    break

            if shell_channel.exit_status_ready():
                while shell_channel.recv_ready():
                    chunk = shell_channel.recv(4096).decode("utf-8", errors="replace")
                    chunk_count += 1
                    output += chunk
                break

            elapsed = time.time() - start_time
            if elapsed > 120:
                print(f"  TIMEOUT after {elapsed:.1f}s")
                break

            time.sleep(0.1)

    elapsed = time.time() - start_time
    exit_code = shell_channel.recv_exit_status() if shell_channel.exit_status_ready() else -1

    # Results
    print(f"\n{'=' * 70}")
    print("RESULTS")
    print('=' * 70)
    print(f"Strategy: {strategy}")
    print(f"Elapsed: {elapsed:.1f}s")
    print(f"Exit code: {exit_code}")
    print(f"Chunks received: {chunk_count}")
    print(f"Total bytes: {len(output)}")
    print()

    # Check for serial
    import re
    match = re.search(r'serial:\s*(\S+)', output, re.IGNORECASE)
    if match:
        print(f"✓ Serial found: {match.group(1)}")
    else:
        print("✗ Serial NOT found in output")

    print()
    print("First 500 chars:")
    print(output[:500])
    print()
    print("Last 500 chars:")
    print(output[-500:])

    ngfw_client.close()
    portal_client.close()

if __name__ == '__main__':
    strategy = sys.argv[1] if len(sys.argv) > 1 else 'idle_timeout'

    # Set up logging
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )

    test_invoke_shell_with_tunnel(strategy)
