"""Network component for Shifter range provisioning.

This component creates the network infrastructure for a range:
- Subnet in the Range VPC
- Route table association
"""

import boto3
import pulumi
import pulumi_aws as aws


def _cleanup_orphaned_subnet(vpc_id: str, cidr_block: str) -> None:
    """Check for and delete any orphaned subnet with the given CIDR.

    This handles edge cases where a previous range's subnet wasn't properly
    cleaned up (e.g., cleanup failure, manual intervention, race condition).

    Args:
        vpc_id: The VPC ID to check in.
        cidr_block: The CIDR block to check for.
    """
    ec2 = boto3.client("ec2")

    # Check if a subnet with this CIDR already exists
    response = ec2.describe_subnets(
        Filters=[
            {"Name": "vpc-id", "Values": [vpc_id]},
            {"Name": "cidr-block", "Values": [cidr_block]},
        ]
    )

    subnets = response.get("Subnets", [])
    if not subnets:
        return  # No conflict, proceed normally

    # Found an orphaned subnet - delete it
    subnet_id = subnets[0]["SubnetId"]
    subnet_name = next(
        (tag["Value"] for tag in subnets[0].get("Tags", []) if tag["Key"] == "Name"),
        "unknown",
    )
    pulumi.log.warn(f"Found orphaned subnet {subnet_id} ({subnet_name}) with CIDR {cidr_block}")
    pulumi.log.info("Deleting orphaned subnet to allow new range creation...")

    try:
        ec2.delete_subnet(SubnetId=subnet_id)
        pulumi.log.info(f"Successfully deleted orphaned subnet {subnet_id}")
    except Exception as e:
        # If deletion fails, let Pulumi handle the error with a clear message
        raise RuntimeError(
            f"Cannot create subnet {cidr_block}: orphaned subnet {subnet_id} exists and could not be deleted: {e}"
        ) from e


class NetworkComponent(pulumi.ComponentResource):
    """Creates network infrastructure for a range.

    Attributes:
        subnet: The created subnet resource.
        subnet_id: The subnet ID.
        subnet_cidr: The CIDR block of the subnet.
    """

    subnet: aws.ec2.Subnet
    subnet_id: pulumi.Output[str]
    subnet_cidr: pulumi.Output[str]

    def __init__(
        self,
        name: str,
        range_id: int,
        user_id: int,
        vpc_id: str,
        cidr_prefix: str,
        subnet_index: int,
        route_table_id: str,
        environment: str,
        availability_zone: str,
        opts: pulumi.ResourceOptions | None = None,
    ):
        """Create network infrastructure for a range.

        Args:
            name: Pulumi resource name prefix.
            range_id: The range ID.
            user_id: The user ID who owns this range.
            vpc_id: The VPC ID to create the subnet in.
            cidr_prefix: The CIDR prefix (e.g., "10.1" for 10.1.X.0/24).
            subnet_index: The index for the third octet of the CIDR.
            route_table_id: The route table to associate with.
            environment: Environment name (dev/prod).
            availability_zone: The AZ to create the subnet in (e.g., "us-east-2a").
            opts: Pulumi resource options.
        """
        super().__init__("shifter:range:NetworkComponent", name, None, opts)

        # Calculate subnet CIDR (use subnet_index + 1 to reserve .0 for infra)
        third_octet = subnet_index + 1
        subnet_cidr = f"{cidr_prefix}.{third_octet}.0/24"

        # Defensive check: clean up any orphaned subnet with this CIDR
        # This handles edge cases where a previous range's subnet wasn't properly
        # cleaned up (e.g., cleanup failure, manual intervention, race condition)
        _cleanup_orphaned_subnet(vpc_id, subnet_cidr)

        # Common tags for all resources
        common_tags = {
            "shifter:range_id": str(range_id),
            "shifter:user_id": str(user_id),
            "shifter:environment": environment,
            "ManagedBy": "pulumi",
        }

        # Create subnet
        self.subnet = aws.ec2.Subnet(
            f"{name}-subnet",
            vpc_id=vpc_id,
            cidr_block=subnet_cidr,
            availability_zone=availability_zone,
            tags={
                **common_tags,
                "Name": f"shifter-range-{range_id}",
            },
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Associate with route table
        aws.ec2.RouteTableAssociation(
            f"{name}-rta",
            subnet_id=self.subnet.id,
            route_table_id=route_table_id,
            opts=pulumi.ResourceOptions(parent=self),
        )

        # Export outputs
        self.subnet_id = self.subnet.id
        self.subnet_cidr = self.subnet.cidr_block

        self.register_outputs(
            {
                "subnetId": self.subnet_id,
                "subnetCidr": self.subnet_cidr,
            }
        )
