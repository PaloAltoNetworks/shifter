"""Network component for Shifter range provisioning.

This component creates the network infrastructure for a range:
- Subnet in the Range VPC
- Route table association
"""

from typing import Optional

import pulumi
import pulumi_aws as aws


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
        availability_zone: str = "us-east-2a",
        opts: Optional[pulumi.ResourceOptions] = None,
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
            availability_zone: The AZ to create the subnet in.
            opts: Pulumi resource options.
        """
        super().__init__("shifter:range:NetworkComponent", name, None, opts)

        # Calculate subnet CIDR (use subnet_index + 1 to reserve .0 for infra)
        third_octet = subnet_index + 1
        subnet_cidr = f"{cidr_prefix}.{third_octet}.0/24"

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
