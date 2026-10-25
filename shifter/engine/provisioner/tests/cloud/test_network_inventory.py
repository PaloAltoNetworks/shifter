"""Tests for provider-specific network inventory adapters."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from cloud.aws.network import AWSNetworkInventory
from cloud.exceptions import CloudNetworkInventoryError
from cloud.gcp.network import GCPNetworkInventory
from config import GDCNetworkAccessConfig


class TestAWSNetworkInventory:
    """AWS network inventory behavior."""

    def test_list_subnet_cidrs_reads_ec2_subnets(self):
        inventory = AWSNetworkInventory()
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {
            "Subnets": [{"CidrBlock": "10.1.2.0/28"}, {"CidrBlock": "10.1.2.16/28"}]
        }

        with patch("boto3.client", return_value=mock_ec2):
            result = inventory.list_subnet_cidrs("vpc-123")

        assert result == ["10.1.2.0/28", "10.1.2.16/28"]

    def test_publish_subnet_exhaustion_alarm_emits_cloudwatch_metric(self):
        inventory = AWSNetworkInventory()
        mock_cloudwatch = MagicMock()

        with patch("boto3.client", return_value=mock_cloudwatch):
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
            patch("boto3.client", return_value=mock_ec2),
            pytest.raises(CloudNetworkInventoryError, match="Failed to list AWS subnet CIDRs"),
        ):
            inventory.list_subnet_cidrs("vpc-missing")


class TestGCPNetworkInventory:
    """GCP network inventory behavior."""

    @patch.dict("os.environ", {"CLOUD_PROVIDER": "aws"}, clear=True)
    def test_list_subnet_cidrs_requires_gdc_access_bundle(self):
        inventory = GCPNetworkInventory()

        with pytest.raises(CloudNetworkInventoryError, match="GDC access configuration"):
            inventory.list_subnet_cidrs("range-network")

    def test_list_subnet_cidrs_reads_managed_gdc_networks_when_access_bundle_present(self, mocker):
        mock_custom_api = MagicMock()
        mock_custom_api.list_cluster_custom_object.return_value = {
            "items": [
                {
                    "metadata": {
                        "name": "range-42-attack",
                        "labels": {
                            "app.kubernetes.io/managed-by": "shifter-provisioner",
                            "shifter.dev/range-plane": "gdc-vmruntime",
                        },
                        "annotations": {"shifter.dev/subnet-cidr": "10.200.0.96/28"},
                    },
                    "spec": {"routes": []},
                },
                {
                    "metadata": {
                        "name": "range-43-attack",
                        "labels": {
                            "app.kubernetes.io/managed-by": "shifter-provisioner",
                            "shifter.dev/range-plane": "gdc-vmruntime",
                        },
                    },
                    "spec": {"routes": [{"to": "10.200.0.112/28"}]},
                },
                {
                    "metadata": {"name": "pod-network"},
                    "spec": {"routes": [{"to": "192.168.0.0/16"}]},
                },
            ]
        }
        kubeconfigs: list[str] = []
        inventory = GCPNetworkInventory(
            gdc_custom_objects_api_factory=lambda kubeconfig: kubeconfigs.append(kubeconfig) or mock_custom_api
        )

        mocker.patch(
            "cloud.gcp.network.load_gdc_network_access_config",
            return_value=GDCNetworkAccessConfig(
                access_secret_id="projects/test/secrets/gdc-access",
                kubeconfig="apiVersion: v1\nclusters: []\ncontexts: []\ncurrent-context: ''\nusers: []\n",
                cluster_id="cluster1",
                vxlan_cidr="10.200.0.0/24",
                region="us-central1",
            ),
        )
        with patch.dict("os.environ", {"CLOUD_PROVIDER": "aws"}, clear=True):
            result = inventory.list_subnet_cidrs("cluster1")

        assert result == ["10.200.0.96/28", "10.200.0.112/28"]
        assert kubeconfigs == ["apiVersion: v1\nclusters: []\ncontexts: []\ncurrent-context: ''\nusers: []\n"]
        mock_custom_api.list_cluster_custom_object.assert_called_once_with(
            group="networking.gke.io",
            version="v1",
            plural="networks",
        )

    def test_list_subnet_cidrs_reads_all_gce_subnetworks_when_backend_is_gce(self):
        mock_client = MagicMock()
        mock_client.aggregated_list.return_value = [
            (
                "regions/us-central1",
                SimpleNamespace(
                    subnetworks=[
                        SimpleNamespace(
                            labels={"managed-by": "shifter-provisioner"},
                            ip_cidr_range="10.50.2.0/28",
                            network="projects/test/global/networks/shifter-range-42",
                        )
                    ]
                ),
            ),
            (
                "regions/us-east4",
                SimpleNamespace(
                    subnetworks=[
                        SimpleNamespace(
                            labels={"managed-by": "other"},
                            ip_cidr_range="10.50.3.0/28",
                            network="projects/test/global/networks/other",
                        )
                    ]
                ),
            ),
        ]
        inventory = GCPNetworkInventory(gce_subnetworks_client_factory=lambda: mock_client)

        with patch.dict(
            "os.environ",
            {
                "CLOUD_PROVIDER": "gcp",
                "GCP_RANGE_BACKEND": "gce",
                "GCP_PROJECT_ID": "test",
                "GCP_REGION": "us-central1",
            },
            clear=True,
        ):
            result = inventory.list_subnet_cidrs("gcp-range-cells:test")

        assert result == ["10.50.2.0/28", "10.50.3.0/28"]
        mock_client.aggregated_list.assert_called_once_with(project="test")

    def test_list_subnet_cidrs_uses_project_from_network_self_link(self):
        # The range VPC's project comes from the network self-link, so the
        # inventory read targets it even when the control-plane GCP_PROJECT_ID is
        # a deploy-overlay placeholder (regression: 404 on the placeholder).
        mock_client = MagicMock()
        mock_client.aggregated_list.return_value = [
            (
                "regions/us-central1",
                SimpleNamespace(
                    subnetworks=[
                        SimpleNamespace(
                            labels={"managed-by": "shifter-provisioner"},
                            ip_cidr_range="10.50.2.0/28",
                            network="projects/real-range-proj/global/networks/shifter-gcp-dev-range",
                        )
                    ]
                ),
            )
        ]
        inventory = GCPNetworkInventory(gce_subnetworks_client_factory=lambda: mock_client)

        with patch.dict(
            "os.environ",
            {
                "CLOUD_PROVIDER": "gcp",
                "GCP_RANGE_BACKEND": "gce",
                "GCP_PROJECT_ID": "placeholder-control-plane",
                "GCP_REGION": "us-central1",
            },
            clear=True,
        ):
            result = inventory.list_subnet_cidrs("projects/real-range-proj/global/networks/shifter-gcp-dev-range")

        assert result == ["10.50.2.0/28"]
        mock_client.aggregated_list.assert_called_once_with(project="real-range-proj")

    def test_list_subnet_cidrs_filters_gce_subnetworks_by_bare_network_id(self):
        mock_client = MagicMock()
        mock_client.aggregated_list.return_value = [
            (
                "regions/us-central1",
                SimpleNamespace(
                    subnetworks=[
                        SimpleNamespace(
                            labels={"managed-by": "shifter-provisioner"},
                            ip_cidr_range="10.50.2.0/28",
                            network="projects/test/global/networks/shifter-range-42",
                        ),
                        SimpleNamespace(
                            labels={"managed-by": "shifter-provisioner"},
                            ip_cidr_range="10.50.3.0/28",
                            network="projects/test/global/networks/shifter-range-43",
                        ),
                    ]
                ),
            ),
            (
                "regions/us-east4",
                SimpleNamespace(
                    subnetworks=[
                        SimpleNamespace(
                            labels={"managed-by": "other"},
                            ip_cidr_range="10.50.4.0/28",
                            network="projects/test/global/networks/shifter-range-42",
                        )
                    ]
                ),
            ),
        ]
        inventory = GCPNetworkInventory(gce_subnetworks_client_factory=lambda: mock_client)

        with patch.dict(
            "os.environ",
            {
                "CLOUD_PROVIDER": "gcp",
                "GCP_RANGE_BACKEND": "gce",
                "GCP_PROJECT_ID": "test",
                "GCP_REGION": "us-central1",
            },
            clear=True,
        ):
            result = inventory.list_subnet_cidrs("shifter-range-42")

        assert result == ["10.50.2.0/28", "10.50.4.0/28"]
        mock_client.aggregated_list.assert_called_once_with(project="test")
