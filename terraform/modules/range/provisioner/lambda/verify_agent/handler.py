"""
Verify Agent Lambda - Checks if XDR agent installed successfully on victim EC2.

Input: { "range_id": int, "retry_count": int (optional) }
Output: {
    "range_id": int,
    "verification_status": "success" | "pending" | "failed",
    "agent_installed": bool,
    "retry_count": int,
    "error": str (optional),
    "message": str (optional)
}

Uses SSM RunCommand to check /var/log/user-data.log for installation status.
Returns verification status for Step Functions decision logic.
"""

import os
import sys
import time

import boto3
from botocore.exceptions import ClientError

# Add shared module to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared import (
    get_db_connection,
    get_logger,
    get_range,
    validate_env_vars,
)

logger = get_logger(__name__)

# Required environment variables for this Lambda
REQUIRED_ENV_VARS = [
    "DB_HOST",
    "DB_NAME",
]

# SSM command to check if user data completed successfully
# Looks for completion marker in user-data.log
VERIFICATION_COMMAND = """#!/bin/bash
set -e

LOG_FILE="/var/log/user-data.log"

if [ ! -f "$LOG_FILE" ]; then
    echo "AGENT_PENDING"
    echo "User data log not found yet"
    exit 2
fi

if grep -q "Victim instance setup complete" "$LOG_FILE" 2>/dev/null; then
    echo "AGENT_INSTALLED"
    exit 0
elif grep -qi "error\\|failed\\|fatal" "$LOG_FILE" 2>/dev/null; then
    echo "AGENT_FAILED"
    echo "Errors found in user-data.log:"
    grep -i "error\\|failed\\|fatal" "$LOG_FILE" | tail -10
    exit 1
else
    echo "AGENT_PENDING"
    echo "Installation still in progress"
    tail -5 "$LOG_FILE"
    exit 2
fi
"""


def handler(event: dict, context) -> dict:
    """
    Verify XDR agent installation on victim EC2 via SSM.

    1. Get victim_instance_id from database
    2. Send SSM RunCommand to check user-data.log
    3. Parse result and return verification status
    """
    # Validate required environment variables early
    validate_env_vars(REQUIRED_ENV_VARS)

    range_id = event["range_id"]
    retry_count = event.get("retry_count", 0)

    logger.info(f"Verifying agent for range {range_id}, attempt {retry_count + 1}")

    # Connect to database
    conn = get_db_connection()
    try:
        # Get range details
        range_data = get_range(conn, range_id)
        if not range_data:
            raise ValueError(f"Range {range_id} not found")

        # Validate range is in provisioning state
        if range_data["status"] != "provisioning":
            raise ValueError(
                f"Range {range_id} is not in provisioning state: {range_data['status']}"
            )

        victim_instance_id = range_data["victim_instance_id"]
        if not victim_instance_id:
            raise ValueError(f"Range {range_id} has no victim_instance_id")

        # Send SSM command
        ssm = boto3.client("ssm")

        try:
            response = ssm.send_command(
                InstanceIds=[victim_instance_id],
                DocumentName="AWS-RunShellScript",
                Parameters={"commands": [VERIFICATION_COMMAND]},
                TimeoutSeconds=60,
                Comment=f"Shifter agent verification for range {range_id}",
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "InvalidInstanceId":
                # SSM agent not ready yet - this is expected early in boot
                logger.info(f"SSM agent not ready on {victim_instance_id}")
                return {
                    "range_id": range_id,
                    "verification_status": "pending",
                    "agent_installed": False,
                    "retry_count": retry_count + 1,
                    "message": "SSM agent not ready yet",
                }
            raise

        command_id = response["Command"]["CommandId"]
        logger.info(f"SSM command {command_id} sent to {victim_instance_id}")

        # Wait for command completion (poll with small delays)
        max_wait = 30  # seconds
        wait_interval = 3
        waited = 0
        status = None
        result = None

        while waited < max_wait:
            time.sleep(wait_interval)
            waited += wait_interval

            try:
                result = ssm.get_command_invocation(
                    CommandId=command_id,
                    InstanceId=victim_instance_id,
                )
                status = result["Status"]
                if status in ["Success", "Failed", "TimedOut", "Cancelled"]:
                    break
            except ClientError as e:
                # Command may not be ready yet
                if "InvocationDoesNotExist" in str(e):
                    continue
                raise

        logger.info(f"SSM command status: {status}")

        # Parse result
        if result:
            stdout = result.get("StandardOutputContent", "").strip()
            stderr = result.get("StandardErrorContent", "").strip()

            if status == "Success" and "AGENT_INSTALLED" in stdout:
                logger.info(f"Agent verified on range {range_id}")
                return {
                    "range_id": range_id,
                    "verification_status": "success",
                    "agent_installed": True,
                    "retry_count": retry_count + 1,
                    "message": "Agent installation verified",
                }

            if status == "Failed" or "AGENT_FAILED" in stdout:
                error_output = stdout + "\n" + stderr
                logger.error(f"Agent installation failed: {error_output}")
                return {
                    "range_id": range_id,
                    "verification_status": "failed",
                    "agent_installed": False,
                    "retry_count": retry_count + 1,
                    "error": f"Agent installation failed: {error_output[:500]}",
                    "message": "Agent installation failed",
                }

        # Still pending - return for retry
        message = "Agent installation still in progress"
        if result:
            stdout = result.get("StandardOutputContent", "").strip()
            if stdout:
                message = stdout[:200]

        return {
            "range_id": range_id,
            "verification_status": "pending",
            "agent_installed": False,
            "retry_count": retry_count + 1,
            "message": message,
        }

    finally:
        conn.close()
