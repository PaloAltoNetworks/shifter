"""Tests for pod-backed mixed-asset lifecycle on GDC."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from config import GDCNetworkAccessConfig, GDCScenarioPodConfig, GDCScenarioPodProfile
from gdc_scenario_pods import apply_range_assets, destroy_range_assets, run_power_operation


class TestApplyRangeAssets:
    @patch("gdc_scenario_pods._build_kube_api_client", return_value=object())
    @patch("gdc_scenario_pods.load_gdc_scenario_pod_config")
    @patch("gdc_scenario_pods.load_gdc_network_access_config")
    def test_apply_range_assets_creates_pod_with_deterministic_network_annotation(
        self,
        mock_access,
        mock_pod_config,
        mock_client_builder,
    ):
        core_api = MagicMock()
        fake_client_module = SimpleNamespace(
            CoreV1Api=MagicMock(return_value=core_api),
        )
        fake_api_exception = type("ApiException", (Exception,), {"status": 500})
        mock_access.return_value = GDCNetworkAccessConfig(
            access_secret_id="projects/test/secrets/shifter-gcp-dev-gdc-access",
            kubeconfig="apiVersion: v1\nclusters: []\ncontexts: []\ncurrent-context: ''\nusers: []\n",
            cluster_id="cluster1",
            vxlan_cidr="10.200.0.0/24",
            region="us-central1",
        )
        mock_pod_config.return_value = GDCScenarioPodConfig(
            image_pull_policy="IfNotPresent",
            ubuntu=GDCScenarioPodProfile(image="docker.io/library/ubuntu:24.04"),
            kali=GDCScenarioPodProfile(image="docker.io/kalilinux/kali-rolling:latest"),
        )

        with (
            patch(
                "gdc_scenario_pods._import_kubernetes_modules",
                return_value=(fake_client_module, None, fake_api_exception),
            ),
            patch("gdc_scenario_pods._wait_for_pod_ready"),
        ):
            result = apply_range_assets(
                "req-123",
                {
                    "range_id": 42,
                    "subnets": [
                        {
                            "name": "mixed",
                            "instances": [
                                {
                                    "uuid": "pod-uuid-1",
                                    "name": "lower-fidelity-target",
                                    "asset_type": "scenario_pod",
                                    "role": "victim",
                                    "os_type": "ubuntu",
                                }
                            ],
                        }
                    ],
                },
                {
                    "mixed": {
                        "gdc_namespace": "range-42",
                        "gdc_network_name": "range-42-mixed",
                        "gdc_nad_name": "range-42-mixed",
                        "gdc_asset_ip_assignments": {"pod-uuid-1": "10.200.0.107"},
                    }
                },
            )

        core_api.create_namespaced_pod.assert_called_once()
        pod_body = core_api.create_namespaced_pod.call_args.kwargs["body"]
        networks_annotation = json.loads(pod_body["metadata"]["annotations"]["k8s.v1.cni.cncf.io/networks"])
        assert networks_annotation == [
            {
                "name": "range-42-mixed",
                "interface": "net1",
                "ips": ["10.200.0.107"],
            }
        ]
        assert pod_body["spec"]["containers"][0]["image"] == "docker.io/library/ubuntu:24.04"
        assert result == [
            {
                "uuid": "pod-uuid-1",
                "name": "lower-fidelity-target",
                "asset_type": "scenario_pod",
                "hostname": "lower-fidelity-target",
                "role": "victim",
                "os": "ubuntu",
                "subnet_name": "mixed",
                "instance_id": "range-42-mixed-victim-1-pod",
                "private_ip": "10.200.0.107",
                "ssh_key_secret_arn": "",
                "ssh_username": "",
                "gdc_pod_name": "range-42-mixed-victim-1-pod",
                "gdc_namespace": "range-42",
                "gdc_network_name": "range-42-mixed",
                "gdc_nad_name": "range-42-mixed",
                "gdc_ip": "10.200.0.107",
                "gdc_interface_name": "net1",
                "gdc_container_image": "docker.io/library/ubuntu:24.04",
            }
        ]


class TestDestroyRangeAssets:
    @patch("gdc_scenario_pods._build_kube_api_client", return_value=object())
    @patch("gdc_scenario_pods.load_gdc_network_access_config")
    def test_destroy_range_assets_deletes_only_pod_backed_assets(self, mock_access, mock_client_builder):
        core_api = MagicMock()
        fake_client_module = SimpleNamespace(
            CoreV1Api=MagicMock(return_value=core_api),
        )
        fake_api_exception = type("ApiException", (Exception,), {"status": 500})
        mock_access.return_value = GDCNetworkAccessConfig(
            access_secret_id="projects/test/secrets/shifter-gcp-dev-gdc-access",
            kubeconfig="apiVersion: v1\nclusters: []\ncontexts: []\ncurrent-context: ''\nusers: []\n",
            cluster_id="cluster1",
            vxlan_cidr="10.200.0.0/24",
            region="us-central1",
        )

        with (
            patch(
                "gdc_scenario_pods._import_kubernetes_modules",
                return_value=(fake_client_module, None, fake_api_exception),
            ),
            patch("gdc_scenario_pods._wait_for_pod_deleted"),
        ):
            destroy_range_assets(
                "req-123",
                {
                    "range_id": 42,
                    "subnets": [
                        {
                            "name": "mixed",
                            "instances": [
                                {
                                    "uuid": "pod-uuid-1",
                                    "asset_type": "scenario_pod",
                                    "role": "victim",
                                    "os_type": "ubuntu",
                                },
                                {
                                    "uuid": "vm-uuid-1",
                                    "asset_type": "vm_runtime_vm",
                                    "role": "victim",
                                    "os_type": "windows",
                                },
                            ],
                        }
                    ],
                },
                {
                    "mixed": {
                        "gdc_namespace": "range-42",
                    }
                },
            )

        core_api.delete_namespaced_pod.assert_called_once_with(
            name="range-42-mixed-victim-1-pod",
            namespace="range-42",
        )


class TestRunPowerOperation:
    @patch("gdc_scenario_pods._build_kube_api_client", return_value=object())
    @patch("gdc_scenario_pods.load_gdc_scenario_pod_config")
    @patch("gdc_scenario_pods.load_gdc_network_access_config")
    def test_start_recreates_pod_from_runtime_state(self, mock_access, mock_pod_config, mock_client_builder):
        core_api = MagicMock()
        fake_client_module = SimpleNamespace(
            CoreV1Api=MagicMock(return_value=core_api),
        )
        fake_api_exception = type("ApiException", (Exception,), {"status": 500})
        not_found = fake_api_exception("missing")
        not_found.status = 404

        mock_access.return_value = GDCNetworkAccessConfig(
            access_secret_id="projects/test/secrets/shifter-gcp-dev-gdc-access",
            kubeconfig="apiVersion: v1\nclusters: []\ncontexts: []\ncurrent-context: ''\nusers: []\n",
            cluster_id="cluster1",
            vxlan_cidr="10.200.0.0/24",
            region="us-central1",
        )
        mock_pod_config.return_value = GDCScenarioPodConfig(
            image_pull_policy="IfNotPresent",
            ubuntu=GDCScenarioPodProfile(image="docker.io/library/ubuntu:24.04"),
            kali=GDCScenarioPodProfile(image="docker.io/kalilinux/kali-rolling:latest"),
        )

        with (
            patch(
                "gdc_scenario_pods._import_kubernetes_modules",
                return_value=(fake_client_module, None, fake_api_exception),
            ),
            patch("gdc_scenario_pods._wait_for_pod_ready") as mock_wait,
        ):
            core_api.read_namespaced_pod.side_effect = not_found

            run_power_operation(
                "start",
                {
                    "uuid": "pod-uuid-1",
                    "name": "lower-fidelity-target",
                    "state": {
                        "cloud_provider": "gcp",
                        "asset_type": "scenario_pod",
                        "subnet_name": "mixed",
                        "private_ip": "10.200.0.107",
                        "provider_metadata": {
                            "gcp": {
                                "namespace": "range-42",
                                "pod_name": "range-42-mixed-victim-1-pod",
                                "nad_name": "range-42-mixed",
                                "container_image": "docker.io/library/ubuntu:24.04",
                                "ip": "10.200.0.107",
                            }
                        },
                    },
                },
            )

        core_api.create_namespaced_pod.assert_called_once()
        pod_body = core_api.create_namespaced_pod.call_args.kwargs["body"]
        assert pod_body["metadata"]["name"] == "range-42-mixed-victim-1-pod"
        assert pod_body["spec"]["containers"][0]["image"] == "docker.io/library/ubuntu:24.04"
        mock_wait.assert_called_once_with(
            core_api,
            "range-42",
            "range-42-mixed-victim-1-pod",
            "10.200.0.107",
            "range-42-mixed",
            fake_api_exception,
        )

    @patch("gdc_scenario_pods._build_kube_api_client", return_value=object())
    @patch("gdc_scenario_pods.load_gdc_scenario_pod_config")
    @patch("gdc_scenario_pods.load_gdc_network_access_config")
    def test_stop_deletes_pod_and_waits(self, mock_access, mock_pod_config, mock_client_builder):
        core_api = MagicMock()
        fake_client_module = SimpleNamespace(
            CoreV1Api=MagicMock(return_value=core_api),
        )
        fake_api_exception = type("ApiException", (Exception,), {"status": 500})

        mock_access.return_value = GDCNetworkAccessConfig(
            access_secret_id="projects/test/secrets/shifter-gcp-dev-gdc-access",
            kubeconfig="apiVersion: v1\nclusters: []\ncontexts: []\ncurrent-context: ''\nusers: []\n",
            cluster_id="cluster1",
            vxlan_cidr="10.200.0.0/24",
            region="us-central1",
        )
        mock_pod_config.return_value = GDCScenarioPodConfig(
            image_pull_policy="IfNotPresent",
            ubuntu=GDCScenarioPodProfile(image="docker.io/library/ubuntu:24.04"),
            kali=GDCScenarioPodProfile(image="docker.io/kalilinux/kali-rolling:latest"),
        )

        with (
            patch(
                "gdc_scenario_pods._import_kubernetes_modules",
                return_value=(fake_client_module, None, fake_api_exception),
            ),
            patch("gdc_scenario_pods._wait_for_pod_deleted") as mock_wait,
        ):
            run_power_operation(
                "stop",
                {
                    "uuid": "pod-uuid-1",
                    "name": "lower-fidelity-target",
                    "state": {
                        "cloud_provider": "gcp",
                        "asset_type": "scenario_pod",
                        "subnet_name": "mixed",
                        "private_ip": "10.200.0.107",
                        "provider_metadata": {
                            "gcp": {
                                "namespace": "range-42",
                                "pod_name": "range-42-mixed-victim-1-pod",
                                "nad_name": "range-42-mixed",
                                "container_image": "docker.io/library/ubuntu:24.04",
                                "ip": "10.200.0.107",
                            }
                        },
                    },
                },
            )

        core_api.delete_namespaced_pod.assert_called_once_with(
            name="range-42-mixed-victim-1-pod",
            namespace="range-42",
        )
        mock_wait.assert_called_once_with(
            core_api,
            "range-42",
            "range-42-mixed-victim-1-pod",
            fake_api_exception,
        )
