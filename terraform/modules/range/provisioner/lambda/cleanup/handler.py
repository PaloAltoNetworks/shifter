"""
Cleanup Lambda - Deletes all resources for a range (idempotent).

Input: { "range_id": "uuid", "mark_failed": true/false }
Output: { "range_id": "uuid", "cleaned_up": [...] }

Called on:
- Provisioning failure (mark_failed=true)
- User-initiated destroy (mark_failed=false, status set to 'destroyed')
- Stale range cleanup (mark_failed=true)
"""

import logging
import os
import sys
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

# Add shared module to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared import get_db_connection, get_range, update_range

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event: dict, context) -> dict:
    """
    Clean up all AWS resources for a range.

    1. Read Range from RDS to get all resource IDs
    2. Delete each resource if exists (idempotent)
    3. Update Range: clear resource fields, set status

    All operations are idempotent - safe to retry.
    """
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
        # Valid states: destroying (user-initiated), provisioning (failure), failed (stale cleanup)
        valid_cleanup_states = {"destroying", "provisioning", "failed"}
        if range_data["status"] not in valid_cleanup_states:
            raise ValueError(
                f"Range {range_id} cannot be cleaned up in state: {range_data['status']}. "
                f"Valid states: {valid_cleanup_states}"
            )

        # 1. Terminate victim EC2 instance
        victim_instance_id = range_data.get("victim_instance_id")
        if victim_instance_id:
            try:
                ec2.terminate_instances(InstanceIds=[victim_instance_id])
                logger.info(f"Terminated instance {victim_instance_id}")
                cleaned_up.append(f"instance:{victim_instance_id}")

                # Wait for termination to complete before deleting subnet
                waiter = ec2.get_waiter("instance_terminated")
                waiter.wait(
                    InstanceIds=[victim_instance_id],
                    WaiterConfig={"Delay": 5, "MaxAttempts": 60},
                )
            except ClientError as e:
                if e.response["Error"]["Code"] == "InvalidInstanceID.NotFound":
                    logger.info(f"Instance {victim_instance_id} already terminated")
                else:
                    raise

        # 2. Delete subnet
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

        # 3. Update database
        update_fields = {
            "victim_instance_id": None,
            "victim_ip": None,
            "subnet_id": None,
            "subnet_cidr": None,
            "chat_url": None,
        }

        if mark_failed:
            update_fields["status"] = "failed"
            update_fields["error_message"] = error_message
        else:
            update_fields["status"] = "destroyed"
            update_fields["destroyed_at"] = datetime.now(timezone.utc)

        update_range(conn, range_id, **update_fields)
        logger.info(f"Updated range {range_id} status")

        return {
            "range_id": range_id,
            "cleaned_up": cleaned_up,
        }

    finally:
        conn.close()
