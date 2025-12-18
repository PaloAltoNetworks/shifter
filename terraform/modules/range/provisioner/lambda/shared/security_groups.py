"""Security group utilities for provisioner Lambda functions."""

import logging

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


def ensure_ssh_from_portal(security_group_id: str, portal_vpc_cidr: str) -> bool:
    """
    Ensure the security group allows SSH (port 22) from the Portal VPC.

    This is idempotent - if the rule already exists, it will be skipped.
    This fixes the recurring issue where range security groups don't have
    SSH rules from Portal VPC because the range terraform isn't re-applied
    after the rules are added to the module.

    Args:
        security_group_id: The security group ID to update
        portal_vpc_cidr: The Portal VPC CIDR block (e.g., "10.0.0.0/16")

    Returns:
        True if rule was added or already exists, False on error
    """
    ec2 = boto3.client("ec2")

    try:
        # Check if rule already exists
        response = ec2.describe_security_group_rules(
            Filters=[
                {"Name": "group-id", "Values": [security_group_id]},
            ]
        )

        # Look for existing SSH rule from portal VPC
        for rule in response.get("SecurityGroupRules", []):
            if (
                not rule.get("IsEgress")
                and rule.get("IpProtocol") == "tcp"
                and rule.get("FromPort") == 22
                and rule.get("ToPort") == 22
                and rule.get("CidrIpv4") == portal_vpc_cidr
            ):
                logger.info(
                    f"SSH rule from {portal_vpc_cidr} already exists in {security_group_id}"
                )
                return True

        # Rule doesn't exist, add it
        logger.info(f"Adding SSH rule from {portal_vpc_cidr} to {security_group_id}")
        ec2.authorize_security_group_ingress(
            GroupId=security_group_id,
            IpPermissions=[
                {
                    "IpProtocol": "tcp",
                    "FromPort": 22,
                    "ToPort": 22,
                    "IpRanges": [
                        {
                            "CidrIp": portal_vpc_cidr,
                            "Description": "SSH from Portal VPC (browser terminal)",
                        }
                    ],
                }
            ],
        )
        logger.info(f"Successfully added SSH rule to {security_group_id}")
        return True

    except ClientError as e:
        # Handle duplicate rule error gracefully (race condition)
        if e.response["Error"]["Code"] == "InvalidPermission.Duplicate":
            logger.info(f"SSH rule already exists (race condition): {security_group_id}")
            return True
        logger.error(f"Failed to ensure SSH rule: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error ensuring SSH rule: {e}")
        return False
