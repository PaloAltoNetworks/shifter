"""Tests for GDC custom L2 range-network provisioning."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from config import GDCNetworkAccessConfig
from gdc_range_networks import (
    _compute_asset_ip_assignments,
    _compute_network_allocation,
    apply_range_networks,
    destroy_range_networks,
)


class TestAllocationHelpers:
    def test_compute_network_allocation_reserves_gateway_and_static_ips(self):
        gateway_ip, static_ips, exclude = _compute_network_allocation(
            "10.200.0.96/28",
            static_ip_reservation_count=4,
        )

        assert gateway_ip == "10.200.0.110"
        assert static_ips == ["10.200.0.106", "10.200.0.107", "10.200.0.108", "10.200.0.109"]
        assert exclude == [
            "10.200.0.106/32",
            "10.200.0.107/32",
            "10.200.0.108/32",
            "10.200.0.109/32",
            "10.200.0.110/32",
        ]

    def test_compute_asset_ip_assignments_keeps_pod_ips_out_of_exclude_list(self):
        gateway_ip, reserved_static_ips, exclude, assignments = _compute_asset_ip_assignments(
            "10.200.0.96/28",
            static_ip_reservation_count=4,
            instances=[
                {"uuid": "vm-1", "asset_type": "vm_runtime_vm"},
                {"uuid": "pod-1", "asset_type": "scenario_pod"},
            ],
        )

        assert gateway_ip == "10.200.0.110"
        assert reserved_static_ips == ["10.200.0.106", "10.200.0.107", "10.200.0.108", "10.200.0.109"]
        assert assignments == {
            "vm-1": "10.200.0.106",
            "pod-1": "10.200.0.107",
        }
        assert exclude == [
            "10.200.0.108/32",
            "10.200.0.109/32",
            "10.200.0.106/32",
            "10.200.0.110/32",
        ]


class TestRangeNetworkProvisioning:
    @patch("gdc_range_networks._build_kube_api_client", return_value=object())
    @patch("gdc_range_networks.load_gdc_network_access_config")
    def test_apply_range_networks_creates_namespace_network_and_nad(self, mock_access, mock_client_builder):
        core_api = MagicMock()
        custom_api = MagicMock()
        fake_client_module = SimpleNamespace(
            CoreV1Api=MagicMock(return_value=core_api),
            CustomObjectsApi=MagicMock(return_value=custom_api),
        )
        fake_api_exception = type("ApiException", (Exception,), {"status": 500})
        mock_access.return_value = GDCNetworkAccessConfig(
            access_secret_id="projects/test/secrets/shifter-gcp-dev-gdc-access",
            kubeconfig="apiVersion: v1\nclusters: []\ncontexts: []\ncurrent-context: ''\nusers: []\n",
            cluster_id="cluster1",
            vxlan_cidr="10.200.0.0/24",
            region="us-central1",
        )

        with patch(
            "gdc_range_networks._import_kubernetes_modules",
            return_value=(None, fake_client_module, None, fake_api_exception),
        ):
            result = apply_range_networks(
                "req-123",
                {
                    "range_id": 42,
                    "subnets": [
                        {
                            "name": "attack",
                            "uuid": "subnet-uuid-1",
                            "cidr": "10.200.0.96/28",
                            "instances": [{"uuid": f"inst-{i}"} for i in range(6)],
                        }
                    ],
                },
            )

        core_api.create_namespace.assert_called_once()
        custom_api.create_cluster_custom_object.assert_called_once()
        custom_api.create_namespaced_custom_object.assert_called_once()
        subnet = result["subnets"]["attack"]
        assert subnet["subnet_id"] == "range-42-attack"
        assert subnet["gdc_namespace"] == "range-42"
        assert subnet["gdc_gateway_ip"] == "10.200.0.110"
        assert subnet["gdc_reserved_static_ips"] == [
            "10.200.0.104",
            "10.200.0.105",
            "10.200.0.106",
            "10.200.0.107",
            "10.200.0.108",
            "10.200.0.109",
        ]
        assert subnet["gdc_asset_ip_assignments"] == {
            "inst-0": "10.200.0.104",
            "inst-1": "10.200.0.105",
            "inst-2": "10.200.0.106",
            "inst-3": "10.200.0.107",
            "inst-4": "10.200.0.108",
            "inst-5": "10.200.0.109",
        }
        assert result["instances"] == []

    @patch("gdc_range_networks._build_kube_api_client", return_value=object())
    @patch("gdc_range_networks.load_gdc_network_access_config")
    def test_destroy_range_networks_deletes_nad_network_and_namespace(self, mock_access, mock_client_builder):
        core_api = MagicMock()
        custom_api = MagicMock()
        fake_client_module = SimpleNamespace(
            CoreV1Api=MagicMock(return_value=core_api),
            CustomObjectsApi=MagicMock(return_value=custom_api),
        )
        fake_api_exception = type("ApiException", (Exception,), {"status": 500})
        mock_access.return_value = GDCNetworkAccessConfig(
            access_secret_id="projects/test/secrets/shifter-gcp-dev-gdc-access",
            kubeconfig="apiVersion: v1\nclusters: []\ncontexts: []\ncurrent-context: ''\nusers: []\n",
            cluster_id="cluster1",
            vxlan_cidr="10.200.0.0/24",
            region="us-central1",
        )

        with patch(
            "gdc_range_networks._import_kubernetes_modules",
            return_value=(None, fake_client_module, None, fake_api_exception),
        ):
            destroy_range_networks(
                "req-123",
                {
                    "range_id": 42,
                    "subnets": [
                        {
                            "name": "attack",
                        }
                    ],
                },
            )

        custom_api.delete_namespaced_custom_object.assert_called_once()
        custom_api.delete_cluster_custom_object.assert_called_once()
        core_api.delete_namespace.assert_called_once_with(name="range-42")
