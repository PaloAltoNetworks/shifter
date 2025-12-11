"""
Create Subnet Lambda - Creates a dedicated subnet for a range in the Range VPC.

Input: { "range_id": "uuid" }
Output: { "range_id": "uuid", "subnet_id": "subnet-xxx", "subnet_cidr": "10.1.X.0/24" }
"""

import logging
import os
import sys

import boto3

# Add shared module to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared import get_db_connection, get_range, get_resource_tags, update_range

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event: dict, context) -> dict:
    """
    Create a subnet for the range in the Range VPC.

    1. Read Range from RDS to get subnet_index
    2. Calculate CIDR: 10.1.{subnet_index}.0/24
    3. Create subnet in Range VPC
    4. Associate with route table
    5. Update Range: subnet_id, subnet_cidr
    """
    range_id = event["range_id"]
    logger.info(f"Creating subnet for range {range_id}")

    # Get configuration from environment
    range_vpc_id = os.environ["RANGE_VPC_ID"]
    range_route_table_id = os.environ["RANGE_ROUTE_TABLE_ID"]
    availability_zone = os.environ.get("AVAILABILITY_ZONE", "us-east-2a")
    environment = os.environ.get("ENVIRONMENT", "prod")

    # Connect to database
    conn = get_db_connection()
    try:
        # Get range details
        range_data = get_range(conn, range_id)
        if not range_data:
            raise ValueError(f"Range {range_id} not found")

        subnet_index = range_data["subnet_index"]
        if subnet_index is None:
            raise ValueError(f"Range {range_id} has no subnet_index assigned")

        user_id = range_data["user_id"]

        # Check if subnet already exists (idempotent)
        if range_data["subnet_id"]:
            logger.info(f"Subnet already exists: {range_data['subnet_id']}")
            return {
                "range_id": range_id,
                "subnet_id": range_data["subnet_id"],
                "subnet_cidr": range_data["subnet_cidr"],
            }

        # Calculate CIDR block
        # Range VPC is 10.1.0.0/16, each range gets 10.1.{index}.0/24
        subnet_cidr = f"10.1.{subnet_index}.0/24"
        logger.info(f"Creating subnet with CIDR {subnet_cidr}")

        # Create subnet
        ec2 = boto3.client("ec2")
        tags = get_resource_tags(range_id, user_id, environment)
        tags.append({"Key": "Name", "Value": f"shifter-range-{range_id[:8]}"})

        response = ec2.create_subnet(
            VpcId=range_vpc_id,
            CidrBlock=subnet_cidr,
            AvailabilityZone=availability_zone,
            TagSpecifications=[
                {
                    "ResourceType": "subnet",
                    "Tags": tags,
                }
            ],
        )
        subnet_id = response["Subnet"]["SubnetId"]
        logger.info(f"Created subnet {subnet_id}")

        # Enable auto-assign public IP (for XDR agent connectivity)
        ec2.modify_subnet_attribute(
            SubnetId=subnet_id,
            MapPublicIpOnLaunch={"Value": True},
        )

        # Associate with route table
        ec2.associate_route_table(
            SubnetId=subnet_id,
            RouteTableId=range_route_table_id,
        )
        logger.info(f"Associated subnet with route table {range_route_table_id}")

        # Update database
        update_range(
            conn,
            range_id,
            subnet_id=subnet_id,
            subnet_cidr=subnet_cidr,
        )
        logger.info(f"Updated range {range_id} with subnet info")

        return {
            "range_id": range_id,
            "subnet_id": subnet_id,
            "subnet_cidr": subnet_cidr,
        }

    finally:
        conn.close()
