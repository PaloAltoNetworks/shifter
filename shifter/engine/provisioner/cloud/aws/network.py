"""AWS network inventory adapter for subnet allocation and alerting."""

from __future__ import annotations

import logging
import os

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from cloud.exceptions import CloudNetworkInventoryError

logger = logging.getLogger(__name__)


class AWSNetworkInventory:
    """EC2 and CloudWatch implementation of NetworkInventory."""

    def _get_client(self, service_name: str):
        region = os.environ.get("AWS_REGION", "us-east-2")
        endpoint_url = os.environ.get("AWS_ENDPOINT_URL") or None
        return boto3.client(service_name, region_name=region, endpoint_url=endpoint_url)

    def list_subnet_cidrs(self, network_id: str) -> list[str]:
        logger.debug("list_subnet_cidrs: vpc_id=%s", network_id)
        try:
            ec2 = self._get_client("ec2")
            response = ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [network_id]}])
            return [subnet["CidrBlock"] for subnet in response.get("Subnets", []) if subnet.get("CidrBlock")]
        except (ClientError, BotoCoreError) as e:
            logger.error("list_subnet_cidrs: failed vpc_id=%s error=%s", network_id, e)
            raise CloudNetworkInventoryError(f"Failed to list AWS subnet CIDRs: {e}") from e

    def publish_subnet_exhaustion_alarm(
        self,
        network_id: str,
        cidr_prefix: str,
        subnet_size: int,
    ) -> None:
        try:
            cloudwatch = self._get_client("cloudwatch")
            cloudwatch.put_metric_data(
                Namespace="Shifter/RangeProvisioning",
                MetricData=[
                    {
                        "MetricName": "SubnetExhaustion",
                        "Value": 1,
                        "Unit": "Count",
                        "Dimensions": [
                            {"Name": "VpcId", "Value": network_id},
                            {"Name": "SubnetSize", "Value": str(subnet_size)},
                        ],
                    }
                ],
            )
        except (ClientError, BotoCoreError) as e:
            logger.error("publish_subnet_exhaustion_alarm: failed vpc_id=%s error=%s", network_id, e)
            raise CloudNetworkInventoryError(f"Failed to publish AWS subnet exhaustion alarm: {e}") from e

        logger.error(
            "CRITICAL: Subnet exhaustion in VPC %s. "
            "No free /%d subnet available in prefix %s. "
            "This is user-impacting - investigate immediately.",
            network_id,
            subnet_size,
            cidr_prefix,
        )
