"""Network component for Shifter range provisioning.

This component creates the network infrastructure for a range:
- Subnet in the Range VPC
- Route table association
"""

import ipaddress
import os

import boto3
import pulumi
import pulumi_aws as aws


def _publish_subnet_exhaustion_alarm(vpc_id: str, cidr_prefix: str) -> None:
    """Publish a CloudWatch metric and log for subnet exhaustion.

    This is a critical infrastructure alert - if we run out of subnets,
    users cannot launch ranges. The metric triggers a CloudWatch alarm
    that sends an email notification.

    Args:
        vpc_id: The VPC that has no free subnets.
        cidr_prefix: The CIDR prefix that was searched.
    """
    region = os.environ.get("AWS_REGION", "us-east-2")
    cloudwatch = boto3.client("cloudwatch", region_name=region)

    # Publish metric for CloudWatch alarm
    cloudwatch.put_metric_data(
        Namespace="Shifter/RangeProvisioning",
        MetricData=[
            {
                "MetricName": "SubnetExhaustion",
                "Value": 1,
                "Unit": "Count",
                "Dimensions": [
                    {"Name": "VpcId", "Value": vpc_id},
                ],
            }
        ],
    )

    # Log with distinctive pattern for metric filter
    # This message will also be picked up by the existing "Operation failed" alarm
    pulumi.log.error(
        f"CRITICAL: Subnet exhaustion in VPC {vpc_id}. "
        f"No free /24 subnet available in range {cidr_prefix}.2.0/24 - {cidr_prefix}.254.0/24. "
        "This is user-impacting - investigate immediately."
    )


def _find_free_subnet(vpc_id: str, cidr_prefix: str) -> str:
    """Find a free /24 subnet in the VPC by querying AWS.

    This queries AWS for all existing subnets in the VPC and finds a /24
    that doesn't conflict with any of them. AWS is the source of truth.

    Args:
        vpc_id: The VPC ID to check.
        cidr_prefix: The CIDR prefix (e.g., "10.1" for 10.1.X.0/24).

    Returns:
        A free CIDR block (e.g., "10.1.8.0/24").

    Raises:
        RuntimeError: If no free /24 subnet can be found.
    """
    ec2 = boto3.client("ec2")

    # Get all subnets in this VPC
    response = ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])

    # Parse all existing subnet CIDRs into network objects
    existing_networks = []
    for subnet in response.get("Subnets", []):
        try:
            existing_networks.append(ipaddress.ip_network(subnet["CidrBlock"]))
        except ValueError:
            continue

    pulumi.log.info(f"Found {len(existing_networks)} existing subnets in VPC {vpc_id}")

    # Try /24 subnets starting from .2.0/24 (reserve .0 and .1 for infrastructure)
    # Range: 10.1.2.0/24 through 10.1.254.0/24 (253 possible range subnets)
    for third_octet in range(2, 255):
        candidate_cidr = f"{cidr_prefix}.{third_octet}.0/24"
        candidate_network = ipaddress.ip_network(candidate_cidr)

        # Check if this candidate overlaps with any existing subnet
        has_conflict = False
        for existing in existing_networks:
            if candidate_network.overlaps(existing):
                has_conflict = True
                break

        if not has_conflict:
            pulumi.log.info(f"Found free subnet: {candidate_cidr}")
            return candidate_cidr

    # No free subnet found - this is a critical infrastructure issue
    # Publish alarm before raising exception so ops gets notified
    _publish_subnet_exhaustion_alarm(vpc_id, cidr_prefix)

    raise RuntimeError(
        f"No free /24 subnet available in VPC {vpc_id}. "
        f"All subnets from {cidr_prefix}.2.0/24 to {cidr_prefix}.254.0/24 "
        "are in use or conflict with existing subnets."
    )


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
            route_table_id: The route table to associate with.
            environment: Environment name (dev/prod).
            availability_zone: The AZ to create the subnet in (e.g., "us-east-2a").
            opts: Pulumi resource options.
        """
        super().__init__("shifter:range:NetworkComponent", name, None, opts)

        # Find a free /24 subnet by querying AWS directly
        subnet_cidr = _find_free_subnet(vpc_id, cidr_prefix)

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
