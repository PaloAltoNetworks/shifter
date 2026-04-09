"""Tests for provider-specific network inventory adapters."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from cloud.aws.network import AWSNetworkInventory
from cloud.exceptions import CloudNetworkInventoryError
from cloud.gcp.network import GCPNetworkInventory


class TestAWSNetworkInventory:
    """AWS network inventory behavior."""

    def test_list_subnet_cidrs_reads_ec2_subnets(self):
        inventory = AWSNetworkInventory()
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {
            "Subnets": [{"CidrBlock": "10.1.2.0/28"}, {"CidrBlock": "10.1.2.16/28"}]
        }

        with patch.object(inventory, "_get_client", return_value=mock_ec2):
            result = inventory.list_subnet_cidrs("vpc-123")

        assert result == ["10.1.2.0/28", "10.1.2.16/28"]

    def test_publish_subnet_exhaustion_alarm_emits_cloudwatch_metric(self):
        inventory = AWSNetworkInventory()
        mock_cloudwatch = MagicMock()

        with patch.object(inventory, "_get_client", return_value=mock_cloudwatch):
            inventory.publish_subnet_exhaustion_alarm("vpc-123", "10.1", 28)

        mock_cloudwatch.put_metric_data.assert_called_once()
        metric_data = mock_cloudwatch.put_metric_data.call_args.kwargs["MetricData"][0]
        assert metric_data["MetricName"] == "SubnetExhaustion"
        assert {"Name": "VpcId", "Value": "vpc-123"} in metric_data["Dimensions"]
        assert {"Name": "SubnetSize", "Value": "28"} in metric_data["Dimensions"]

    def test_list_subnet_cidrs_wraps_client_error(self):
        inventory = AWSNetworkInventory()
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.side_effect = ClientError(
            {"Error": {"Code": "InvalidVpcID.NotFound", "Message": "not found"}},
            "DescribeSubnets",
        )

        with (
            patch.object(inventory, "_get_client", return_value=mock_ec2),
            pytest.raises(CloudNetworkInventoryError, match="Failed to list AWS subnet CIDRs"),
        ):
            inventory.list_subnet_cidrs("vpc-missing")


class TestGCPNetworkInventory:
    """GCP network inventory behavior."""

    @patch.dict("os.environ", {"GCP_PROJECT_ID": "shifter-gcp-dev"})
    def test_list_subnet_cidrs_filters_by_network_name(self):
        inventory = GCPNetworkInventory()
        mock_client = MagicMock()
        mock_client.aggregated_list.return_value = [
            (
                "regions/us-central1",
                SimpleNamespace(
                    subnetworks=[
                        SimpleNamespace(
                            network="https://www.googleapis.com/compute/v1/projects/shifter-gcp-dev/global/networks/shifter-gcp-dev-range",
                            ip_cidr_range="10.50.0.0/28",
                        ),
                        SimpleNamespace(
                            network="https://www.googleapis.com/compute/v1/projects/shifter-gcp-dev/global/networks/other",
                            ip_cidr_range="10.60.0.0/28",
                        ),
                    ]
                ),
            )
        ]
        mock_compute_v1 = SimpleNamespace(SubnetworksClient=MagicMock(return_value=mock_client))

        with patch("cloud.gcp.network.import_google_module", return_value=mock_compute_v1):
            result = inventory.list_subnet_cidrs("shifter-gcp-dev-range")

        assert result == ["10.50.0.0/28"]

    @patch.dict("os.environ", {}, clear=True)
    def test_list_subnet_cidrs_requires_project_id(self):
        inventory = GCPNetworkInventory()

        with pytest.raises(CloudNetworkInventoryError, match="GCP project ID is required"):
            inventory.list_subnet_cidrs("range-network")
