"""
Cleanup Lambda - Deletes all resources for a range (idempotent).

Input: { "range_id": "uuid", "mark_failed": true/false }
Output: { "range_id": "uuid", "cleaned_up": [...] }

Called on:
- Provisioning failure (mark_failed=true) - sets status to 'failed'
- User-initiated destroy (mark_failed=false) - status already 'destroyed' by Portal
- Stale range cleanup (mark_failed=true) - sets status to 'failed'

User-initiated destroy is async: Portal sets status to 'destroyed' immediately,
then triggers this Lambda to clean up resources in the background.
"""

import os
import sys

import boto3
from botocore.exceptions import ClientError

# Add shared module to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared import (
    get_db_connection,
    get_logger,
    get_range,
    update_range,
    validate_env_vars,
)

logger = get_logger(__name__)

# Required environment variables for this Lambda
REQUIRED_ENV_VARS = [
    "DB_HOST",
    "DB_NAME",
]


def handler(event: dict, context) -> dict:
    """
    Clean up all AWS resources for a range.

    1. Read Range from RDS to get all resource IDs
    2. Delete each resource if exists (idempotent)
    3. Update Range: clear resource fields, set status

    All operations are idempotent - safe to retry.
    """
    # Validate required environment variables early
    validate_env_vars(REQUIRED_ENV_VARS)

    range_id = event["range_id"]
    mark_failed = event.get("mark_failed", True)
    error_message = event.get("error_message", "Provisioning failed")

    logger.info(f"Cleaning up range {range_id}, mark_failed={mark_failed}")

    cleaned_up = []
    ec2 = boto3.client("ec2")

    # Connect to database
    conn = get_db_connection()
    try:
        # Get range details
        range_data = get_range(conn, range_id)
        if not range_data:
            logger.warning(f"Range {range_id} not found - nothing to clean up")
            return {"range_id": range_id, "cleaned_up": []}

        # Validate range is in a state that allows cleanup
        # Valid states for mark_failed=true: provisioning, failed (error cleanup)
        # Valid states for mark_failed=false: destroyed (Portal already set status)
        if mark_failed:
            valid_cleanup_states = {"provisioning", "failed"}
        else:
            valid_cleanup_states = {"destroyed"}

        if range_data["status"] not in valid_cleanup_states:
            raise ValueError(
                f"Range {range_id} cannot be cleaned up in state: {range_data['status']}. "
                f"Valid states for mark_failed={mark_failed}: {valid_cleanup_states}"
            )

        # Update DB status FIRST so user sees failure immediately
        # Resource cleanup continues in background
        if mark_failed:
            update_range(
                conn,
                range_id,
                status="failed",
                error_message=error_message,
            )
            logger.info(f"Marked range {range_id} as failed - starting resource cleanup")

        # 1. Terminate victim EC2 instance
        victim_instance_id = range_data.get("victim_instance_id")
        if victim_instance_id:
            try:
                ec2.terminate_instances(InstanceIds=[victim_instance_id])
                logger.info(f"Terminated victim instance {victim_instance_id}")
                cleaned_up.append(f"victim:{victim_instance_id}")
            except ClientError as e:
                if e.response["Error"]["Code"] == "InvalidInstanceID.NotFound":
                    logger.info(f"Victim instance {victim_instance_id} already terminated")
                else:
                    raise

        # 2. Terminate Kali EC2 instance
        kali_instance_id = range_data.get("kali_instance_id")
        if kali_instance_id:
            try:
                ec2.terminate_instances(InstanceIds=[kali_instance_id])
                logger.info(f"Terminated Kali instance {kali_instance_id}")
                cleaned_up.append(f"kali:{kali_instance_id}")
            except ClientError as e:
                if e.response["Error"]["Code"] == "InvalidInstanceID.NotFound":
                    logger.info(f"Kali instance {kali_instance_id} already terminated")
                else:
                    raise

        # 3. Delete Kali SSH key secret from Secrets Manager
        secrets_client = boto3.client("secretsmanager")
        kali_ssh_key_secret_arn = range_data.get("kali_ssh_key_secret_arn")
        if kali_ssh_key_secret_arn:
            try:
                secrets_client.delete_secret(
                    SecretId=kali_ssh_key_secret_arn,
                    ForceDeleteWithoutRecovery=True,
                )
                logger.info(f"Deleted Kali SSH key secret {kali_ssh_key_secret_arn}")
                cleaned_up.append(f"secret:{kali_ssh_key_secret_arn}")
            except ClientError as e:
                if e.response["Error"]["Code"] == "ResourceNotFoundException":
                    logger.info(f"Kali SSH key secret {kali_ssh_key_secret_arn} already deleted")
                else:
                    raise

        # 4. Delete Victim SSH key secret from Secrets Manager
        victim_ssh_key_secret_arn = range_data.get("victim_ssh_key_secret_arn")
        if victim_ssh_key_secret_arn:
            try:
                secrets_client.delete_secret(
                    SecretId=victim_ssh_key_secret_arn,
                    ForceDeleteWithoutRecovery=True,
                )
                logger.info(f"Deleted Victim SSH key secret {victim_ssh_key_secret_arn}")
                cleaned_up.append(f"secret:{victim_ssh_key_secret_arn}")
            except ClientError as e:
                if e.response["Error"]["Code"] == "ResourceNotFoundException":
                    logger.info(f"Victim SSH key secret {victim_ssh_key_secret_arn} already deleted")
                else:
                    raise

        # 5. Wait for all instances to terminate before deleting subnet
        instances_to_wait = []
        if victim_instance_id:
            instances_to_wait.append(victim_instance_id)
        if kali_instance_id:
            instances_to_wait.append(kali_instance_id)

        if instances_to_wait:
            waiter = ec2.get_waiter("instance_terminated")
            waiter.wait(
                InstanceIds=instances_to_wait,
                WaiterConfig={"Delay": 5, "MaxAttempts": 60},
            )
            logger.info(f"All instances terminated: {instances_to_wait}")

        # 6. Delete subnet
        subnet_id = range_data.get("subnet_id")
        if subnet_id:
            try:
                # First, delete any route table associations
                associations = ec2.describe_route_tables(
                    Filters=[{"Name": "association.subnet-id", "Values": [subnet_id]}]
                )
                for rt in associations.get("RouteTables", []):
                    for assoc in rt.get("Associations", []):
                        if assoc.get("SubnetId") == subnet_id and not assoc.get("Main"):
                            ec2.disassociate_route_table(
                                AssociationId=assoc["RouteTableAssociationId"]
                            )
                            logger.info(f"Disassociated route table from {subnet_id}")

                # Delete the subnet
                ec2.delete_subnet(SubnetId=subnet_id)
                logger.info(f"Deleted subnet {subnet_id}")
                cleaned_up.append(f"subnet:{subnet_id}")
            except ClientError as e:
                if e.response["Error"]["Code"] == "InvalidSubnetID.NotFound":
                    logger.info(f"Subnet {subnet_id} already deleted")
                elif "DependencyViolation" in str(e):
                    logger.warning(f"Subnet {subnet_id} has dependencies, will retry")
                    raise
                else:
                    raise

        # 7. Update database - clear resource fields
        # Status was already set:
        # - mark_failed=true: set to 'failed' at start of this function
        # - mark_failed=false: set to 'destroyed' by Portal before calling us
        update_range(
            conn,
            range_id,
            victim_instance_id="",
            victim_ip=None,
            victim_ssh_key_secret_arn="",
            kali_instance_id="",
            kali_ip=None,
            kali_ssh_key_secret_arn="",
            subnet_id="",
            subnet_cidr="",
            chat_url="",
        )
        logger.info(f"Cleared resource fields for range {range_id}")

        return {
            "range_id": range_id,
            "cleaned_up": cleaned_up,
        }

    finally:
        conn.close()
