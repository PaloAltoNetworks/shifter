"""
Create Subnet Lambda - Creates a dedicated subnet for a range in the Range VPC.

Input: { "range_id": "uuid" }
Output: { "range_id": "uuid", "subnet_id": "subnet-xxx", "subnet_cidr": "10.1.X.0/24" }
"""

import os
import sys

import boto3
from botocore.exceptions import ClientError

# Add shared module to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared import (
    get_db_connection,
    get_env,
    get_logger,
    get_range,
    get_resource_tags,
    update_range,
    validate_env_vars,
)

logger = get_logger(__name__)

# Required environment variables for this Lambda
REQUIRED_ENV_VARS = [
    "RANGE_VPC_ID",
    "RANGE_ROUTE_TABLE_ID",
    "RANGE_CIDR_PREFIX",
    "DB_HOST",
    "DB_NAME",
]


def get_used_cidrs(ec2_client, vpc_id: str) -> set[int]:
    """Get set of third octets already in use by subnets in the VPC."""
    existing_subnets = ec2_client.describe_subnets(
        Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
    )
    used_octets = set()
    for subnet in existing_subnets["Subnets"]:
        # Parse CIDR like "10.1.5.0/24" to extract third octet (5)
        parts = subnet["CidrBlock"].split(".")
        if len(parts) >= 3:
            used_octets.add(int(parts[2]))
    return used_octets


def find_available_octet(used_octets: set[int], preferred: int) -> int:
    """Find an available third octet, preferring the suggested one."""
    if preferred not in used_octets:
        return preferred
    # Find next available, skipping 0 (reserved for infrastructure)
    for candidate in range(1, 256):
        if candidate not in used_octets:
            return candidate
    raise ValueError("No available CIDR blocks in VPC")


def create_subnet_with_retry(
    ec2_client, vpc_id: str, cidr_prefix: str, az: str, tags: list, preferred_octet: int
) -> tuple[str, str]:
    """Create a subnet, retrying with different CIDRs if conflicts occur."""
    used_octets = get_used_cidrs(ec2_client, vpc_id)

    for _ in range(250):  # Max attempts (/16 has ~255 usable /24s)
        third_octet = find_available_octet(used_octets, preferred_octet)
        subnet_cidr = f"{cidr_prefix}.{third_octet}.0/24"
        logger.info(f"Attempting to create subnet with CIDR {subnet_cidr}")

        try:
            response = ec2_client.create_subnet(
                VpcId=vpc_id,
                CidrBlock=subnet_cidr,
                AvailabilityZone=az,
                TagSpecifications=[{"ResourceType": "subnet", "Tags": tags}],
            )
            subnet_id = response["Subnet"]["SubnetId"]
            logger.info(f"Created subnet {subnet_id}")
            return subnet_id, subnet_cidr
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "InvalidSubnet.Conflict":
                logger.warning(f"CIDR {subnet_cidr} conflicts, trying another")
                used_octets.add(third_octet)
                continue
            raise

    raise ValueError("Failed to create subnet after exhausting available CIDRs")


def handler(event: dict, context) -> dict:
    """
    Create a subnet for the range in the Range VPC.

    1. Read Range from RDS to get subnet_index
    2. Create subnet with available CIDR (handles conflicts gracefully)
    3. Associate with route table
    4. Update Range: subnet_id, subnet_cidr
    """
    validate_env_vars(REQUIRED_ENV_VARS)

    range_id = event["range_id"]
    logger.info(f"Creating subnet for range {range_id}")

    # Get configuration from environment
    range_vpc_id = get_env("RANGE_VPC_ID")
    range_route_table_id = get_env("RANGE_ROUTE_TABLE_ID")
    range_cidr_prefix = get_env("RANGE_CIDR_PREFIX")
    availability_zone = get_env("AVAILABILITY_ZONE", "us-east-2a")
    environment = get_env("ENVIRONMENT", "prod")

    conn = get_db_connection()
    try:
        range_data = get_range(conn, range_id)
        if not range_data:
            raise ValueError(f"Range {range_id} not found")

        if range_data["status"] != "provisioning":
            raise ValueError(
                f"Range {range_id} is not in provisioning state: {range_data['status']}"
            )

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

        # Create subnet with automatic CIDR selection
        ec2 = boto3.client("ec2")
        tags = get_resource_tags(range_id, user_id, environment)
        tags.append({"Key": "Name", "Value": f"shifter-range-{range_id}"})

        # Preferred octet is subnet_index + 1 (reserve .0.0/24 for infrastructure)
        subnet_id, subnet_cidr = create_subnet_with_retry(
            ec2, range_vpc_id, range_cidr_prefix, availability_zone, tags, subnet_index + 1
        )

        # Associate with route table (routes through firewall)
        ec2.associate_route_table(SubnetId=subnet_id, RouteTableId=range_route_table_id)
        logger.info(f"Associated subnet with route table {range_route_table_id}")

        # Update database
        update_range(conn, range_id, subnet_id=subnet_id, subnet_cidr=subnet_cidr)
        logger.info(f"Updated range {range_id} with subnet info")

        return {
            "range_id": range_id,
            "subnet_id": subnet_id,
            "subnet_cidr": subnet_cidr,
        }

    finally:
        conn.close()
