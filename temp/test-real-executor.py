#!/usr/bin/env python3
"""Test actual SSH executor code against live NGFW via tunnel.

Tunnel should be running: localhost:2222 -> portal:22
Portal can reach NGFW at 10.1.7.240
"""

import sys
import os
import time
import boto3

# Add provisioner to path
sys.path.insert(0, '/home/atomik/src/shifter/shifter/engine/provisioner')

from executors.ssh_executor import SSHExecutor

def get_ssh_key():
    """Get SSH key from Secrets Manager."""
    secret_arn = "arn:aws:secretsmanager:us-east-2:878848911818:secret:shifter/dev/ngfw/79248efb-8f53-4fbc-af4b-be03df7f5883/ssh-key-8RoOlq"

    session = boto3.Session(profile_name='panw-shifter-dev-workstation', region_name='us-east-2')
    client = session.client('secretsmanager')
    response = client.get_secret_value(SecretId=secret_arn)
    return response['SecretString']

def test_current_implementation():
    """Test the current SSH executor implementation."""

    print("=" * 70)
    print("Testing CURRENT SSH Executor Implementation")
    print("=" * 70)
    print()

    # Get key
    print("Getting SSH key...")
    key_content = get_ssh_key()

    # Create executor
    print("Creating SSH executor...")
    executor = SSHExecutor(private_key=key_content)

    # Test command
    ngfw_ip = "10.1.7.240"
    print(f"Running 'show system info' on {ngfw_ip}...")
    print()

    start = time.time()
    try:
        result = executor.run_command(
            instance_id=ngfw_ip,
            script="show system info",
            timeout_seconds=120,
        )
        elapsed = time.time() - start

        print(f"✓ Command completed in {elapsed:.1f}s")
        print(f"Exit code: {result.exit_code}")
        print(f"Success: {result.success}")
        print(f"Stdout length: {len(result.stdout)} bytes")
        print(f"Stderr length: {len(result.stderr)} bytes")
        print()
        print("First 500 chars of stdout:")
        print(result.stdout[:500])
        print()
        print("Last 500 chars of stdout:")
        print(result.stdout[-500:])
        print()

        # Check for serial
        import re
        match = re.search(r'serial:\s*(\S+)', result.stdout, re.IGNORECASE)
        if match:
            print(f"✓ Serial found: {match.group(1)}")
        else:
            print("✗ Serial NOT found in output")

    except Exception as e:
        elapsed = time.time() - start
        print(f"✗ Command failed after {elapsed:.1f}s")
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    # Set logging to see debug output from SSH executor
    import logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s [%(name)s] %(levelname)s: %(message)s'
    )

    test_current_implementation()
