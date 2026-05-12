"""Tests for GDC VM Runtime guest lifecycle."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from config import GDCNetworkAccessConfig, GDCVMRuntimeConfig, GDCVMRuntimeProfile
from gdc_vmruntime_assets import (
    _render_user_data,
    _resolve_image_source,
    apply_range_assets,
    destroy_range_assets,
    run_power_operation,
)


class TestImageSourceResolution:
    def test_supports_gcs_with_optional_secret_ref(self):
        assert _resolve_image_source("gs://bucket/image.qcow2", "gdc-vm-image-gcs") == {
            "gcs": {
                "url": "gs://bucket/image.qcow2",
                "secretRef": "gdc-vm-image-gcs",
            }
        }

    def test_supports_registry_aliases(self):
        assert _resolve_image_source("oci://registry.example.com/image:latest", None) == {
            "registry": {
                "url": "docker://registry.example.com/image:latest",
            }
        }

    def test_rejects_plain_http_sources(self):
        try:
            _resolve_image_source("http://example.com/image.qcow2", None)
        except RuntimeError as exc:
            assert "https://" in str(exc)
        else:
            raise AssertionError("plain HTTP image sources must be rejected")


class TestRenderUserData:
    # Per #762: the per-instance guest password is NOT rendered into
    # user_data. The engine provisioner sets it post-boot via SSH using
    # the per-instance SSH key. user_data carries only public material
    # (hostname, SSH public key).
    def test_non_dc_render_does_not_embed_any_password_value(self):
        # The rendered user_data must not carry plaintext credentials
        # for kali/ubuntu/windows victims; absence of literals AND
        # absence of any "chpasswd"/"net user $" form proves this.
        for role, os_type in (("victim", "ubuntu"), ("attacker", "kali"), ("victim", "windows")):
            result = _render_user_data(
                {"role": role, "os_type": os_type},
                hostname="target-01",
                public_key="ssh-rsa AAAA",
            )
            assert "CortexSavesTheDay!" not in result
            # No chpasswd / net user invocation embedded with a value.
            import re

            chpasswd_pattern = re.compile(r'(?:echo\s+["\']?)([a-z]+):\1(?:["\']?\s*\|\s*chpasswd)')
            assert not chpasswd_pattern.search(result), result
            # No gcloud / aws fetch leftover from the prior fetch-at-boot
            # approach — the password is now pushed by the provisioner,
            # not fetched by the guest.
            assert "gcloud secrets versions access" not in result
            assert "aws secretsmanager get-secret-value" not in result

    def test_dc_render_does_not_embed_password(self, monkeypatch):
        # Per #762: even the DC's pre-promote local Administrator
        # password is no longer rendered into user_data. The engine
        # provisioner sets it post-boot via SSH (using the
        # per-instance SSH key already in administrators_authorized_keys)
        # and the DC promote workflow then replaces it with the
        # deployment-scoped DC_DOMAIN_PASSWORD via Ansible/SSM. The
        # rendered user_data must not contain the value regardless of
        # what env var is present.
        monkeypatch.setenv("DC_DOMAIN_PASSWORD", "DomainPass123!")

        result = _render_user_data(
            {"role": "dc", "os_type": "windows"},
            hostname="dc-01",
            public_key="ssh-rsa AAAA",
        )

        assert "DomainPass123!" not in result
        assert "CortexSavesTheDay!" not in result
        # No fetch-at-boot fallback leftovers either.
        assert "gcloud secrets versions access" not in result
        assert "aws secretsmanager get-secret-value" not in result


class TestApplyRangeAssets:
    @patch("gdc_vmruntime_assets._build_kube_api_client", return_value=object())
    @patch("gdc_vmruntime_assets.load_gdc_vmruntime_config")
    @patch("gdc_vmruntime_assets.load_gdc_network_access_config")
    def test_apply_range_assets_creates_disk_and_vm_and_returns_guest_outputs(
        self,
        mock_access,
        mock_vm_config,
        mock_client_builder,
    ):
        custom_api = MagicMock()
        core_api = MagicMock()
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
        mock_vm_config.return_value = GDCVMRuntimeConfig(
            storage_class_name="local-shared",
            image_gcs_secret_id="projects/test/secrets/shifter-gcp-dev-gdc-vm-image-gcs",
            windows=GDCVMRuntimeProfile(
                source_url="gs://images/windows.qcow2",
                vcpus=2,
                memory="8Gi",
                disk_size_gib=64,
            ),
        )

        with (
            patch(
                "gdc_vmruntime_assets._import_kubernetes_modules",
                return_value=(None, fake_client_module, None, fake_api_exception),
            ),
            patch("gdc_vmruntime_assets._ensure_gcs_image_secret", return_value="gdc-vm-image-gcs"),
            patch(
                "gdc_vmruntime_assets._ensure_ssh_secret",
                return_value=("projects/test/secrets/range-42-victim-ssh", "ssh-rsa AAAA"),
            ),
            patch(
                "gdc_vmruntime_assets._ensure_rdp_password_secret",
                return_value=(
                    "projects/test/secrets/range-42-victim-rdp",
                    "PerInstanceP4ss!",
                ),
            ),
            patch("gdc_vmruntime_assets._render_user_data", return_value="<powershell>userdata</powershell>"),
            patch("gdc_vmruntime_assets._wait_for_disk_ready"),
            patch(
                "gdc_vmruntime_assets._wait_for_vm_ready",
                return_value={
                    "status": {
                        "state": "Running",
                        "interfaces": [{"ipAddresses": ["10.200.0.104/28"]}],
                    }
                },
            ),
            patch(
                "gdc_vmruntime_assets._collect_vmi_metadata",
                return_value={"gdc_vmi_name": "range-42-victims-victim-1234", "gdc_node_name": "cluster1-abm-w1-001"},
            ),
        ):
            result = apply_range_assets(
                "req-123",
                {
                    "range_id": 42,
                    "subnets": [
                        {
                            "name": "victims",
                            "instances": [
                                {
                                    "uuid": "instance-1234",
                                    "name": "target-win-01",
                                    "asset_type": "vm_runtime_vm",
                                    "role": "victim",
                                    "os_type": "windows",
                                }
                            ],
                        }
                    ],
                },
                {
                    "victims": {
                        "subnet_cidr": "10.200.0.96/28",
                        "gdc_namespace": "range-42",
                        "gdc_network_name": "range-42-victims",
                        "gdc_nad_name": "range-42-victims",
                        "gdc_reserved_static_ips": ["10.200.0.104"],
                        "gdc_asset_ip_assignments": {"instance-1234": "10.200.0.104"},
                    }
                },
            )

        assert custom_api.create_namespaced_custom_object.call_count == 2
        disk_body = custom_api.create_namespaced_custom_object.call_args_list[0].kwargs["body"]
        vm_body = custom_api.create_namespaced_custom_object.call_args_list[1].kwargs["body"]
        assert disk_body["kind"] == "VirtualMachineDisk"
        assert disk_body["spec"]["source"]["gcs"]["secretRef"] == "gdc-vm-image-gcs"
        assert vm_body["kind"] == "VirtualMachine"
        assert vm_body["spec"]["interfaces"][0]["ipAddresses"] == ["10.200.0.104/28"]

        assert result == [
            {
                "uuid": "instance-1234",
                "name": "target-win-01",
                "asset_type": "vm_runtime_vm",
                "hostname": "target-win-01",
                "role": "victim",
                "os": "windows",
                "subnet_name": "victims",
                "instance_id": "range-42-victims-victim-1234",
                "private_ip": "10.200.0.104",
                "public_key": "ssh-rsa AAAA",
                "ssh_key_secret_arn": "projects/test/secrets/range-42-victim-ssh",
                "rdp_password_secret_arn": "projects/test/secrets/range-42-victim-rdp",
                "gdc_rdp_password_secret_ref": "projects/test/secrets/range-42-victim-rdp",
                "ssh_username": "Administrator",
                "gdc_vm_name": "range-42-victims-victim-1234",
                "gdc_namespace": "range-42",
                "gdc_network_name": "range-42-victims",
                "gdc_nad_name": "range-42-victims",
                "gdc_ip": "10.200.0.104",
                "gdc_interface_name": "eth0",
                "vmruntime_disk_name": "range-42-victims-victim-1234-boot",
                "gdc_vmi_name": "range-42-victims-victim-1234",
                "gdc_node_name": "cluster1-abm-w1-001",
            }
        ]


class TestDestroyRangeAssets:
    @patch("gdc_vmruntime_assets._build_kube_api_client", return_value=object())
    @patch("gdc_vmruntime_assets.load_gdc_vmruntime_config")
    @patch("gdc_vmruntime_assets.load_gdc_network_access_config")
    def test_destroy_range_assets_deletes_vms_disks_and_ssh_secrets(
        self,
        mock_access,
        mock_vm_config,
        mock_client_builder,
    ):
        custom_api = MagicMock()
        core_api = MagicMock()
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
        mock_vm_config.return_value = GDCVMRuntimeConfig(
            storage_class_name="local-shared",
            image_gcs_secret_id="projects/test/secrets/shifter-gcp-dev-gdc-vm-image-gcs",
        )

        with (
            patch(
                "gdc_vmruntime_assets._import_kubernetes_modules",
                return_value=(None, fake_client_module, None, fake_api_exception),
            ),
            patch("gdc_vmruntime_assets._wait_for_deleted"),
            patch("gdc_vmruntime_assets._delete_ssh_secret") as mock_delete_secret,
            patch("gdc_vmruntime_assets._delete_rdp_password_secret") as mock_delete_rdp_secret,
        ):
            destroy_range_assets(
                "req-123",
                {
                    "range_id": 42,
                    "subnets": [
                        {
                            "name": "victims",
                            "instances": [
                                {
                                    "uuid": "instance-1234",
                                    "asset_type": "vm_runtime_vm",
                                    "role": "victim",
                                    "os_type": "windows",
                                }
                            ],
                        }
                    ],
                },
                {
                    "victims": {
                        "gdc_namespace": "range-42",
                    }
                },
            )

        assert custom_api.delete_namespaced_custom_object.call_count == 2
        delete_calls = custom_api.delete_namespaced_custom_object.call_args_list
        assert delete_calls[0].kwargs["plural"] == "virtualmachines"
        assert delete_calls[1].kwargs["plural"] == "virtualmachinedisks"
        mock_delete_secret.assert_called_once()
        mock_delete_rdp_secret.assert_called_once()
        core_api.delete_namespaced_secret.assert_called_once_with(name="gdc-vm-image-gcs", namespace="range-42")

    @patch("gdc_vmruntime_assets._build_kube_api_client", return_value=object())
    @patch("gdc_vmruntime_assets.load_gdc_vmruntime_config")
    @patch("gdc_vmruntime_assets.load_gdc_network_access_config")
    def test_apply_range_assets_ignores_scenario_pod_instances(
        self,
        mock_access,
        mock_vm_config,
        mock_client_builder,
    ):
        custom_api = MagicMock()
        core_api = MagicMock()
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
        mock_vm_config.return_value = GDCVMRuntimeConfig(
            storage_class_name="local-shared",
            image_gcs_secret_id="projects/test/secrets/shifter-gcp-dev-gdc-vm-image-gcs",
            ubuntu=GDCVMRuntimeProfile(source_url="gs://images/ubuntu.qcow2"),
        )

        with (
            patch(
                "gdc_vmruntime_assets._import_kubernetes_modules",
                return_value=(None, fake_client_module, None, fake_api_exception),
            ),
            patch("gdc_vmruntime_assets._ensure_gcs_image_secret", return_value="gdc-vm-image-gcs"),
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
                        "subnet_cidr": "10.200.0.96/28",
                        "gdc_namespace": "range-42",
                        "gdc_network_name": "range-42-mixed",
                        "gdc_nad_name": "range-42-mixed",
                        "gdc_asset_ip_assignments": {"pod-uuid-1": "10.200.0.104"},
                    }
                },
            )

        assert result == []
        custom_api.create_namespaced_custom_object.assert_not_called()


@patch("gdc_vmruntime_assets.subprocess.run")
@patch("gdc_vmruntime_assets._build_kube_api_client", return_value=object())
@patch("gdc_vmruntime_assets.load_gdc_network_access_config")
def test_run_power_operation_starts_vm_and_waits_for_ready(mock_access, mock_client_builder, mock_run):
    custom_api = MagicMock()
    fake_client_module = SimpleNamespace(CustomObjectsApi=MagicMock(return_value=custom_api))
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
            "gdc_vmruntime_assets._import_kubernetes_modules",
            return_value=(None, fake_client_module, None, fake_api_exception),
        ),
        patch("gdc_vmruntime_assets._wait_for_vm_ready") as mock_wait_ready,
    ):
        run_power_operation(
            "start",
            {
                "provider_metadata": {
                    "gcp": {
                        "namespace": "range-42",
                        "vm_name": "range-42-victims-victim-1234",
                    }
                }
            },
        )

    command = mock_run.call_args.args[0]
    assert command[0] == "kubectl"
    assert "virt" in command
    assert "start" in command
    assert "range-42-victims-victim-1234" in command
    assert "range-42" in command
    mock_wait_ready.assert_called_once_with(custom_api, "range-42", "range-42-victims-victim-1234", fake_api_exception)


@patch("gdc_vmruntime_assets.subprocess.run")
@patch("gdc_vmruntime_assets._build_kube_api_client", return_value=object())
@patch("gdc_vmruntime_assets.load_gdc_network_access_config")
def test_run_power_operation_stops_vm_and_waits_for_stopped(mock_access, mock_client_builder, mock_run):
    custom_api = MagicMock()
    fake_client_module = SimpleNamespace(CustomObjectsApi=MagicMock(return_value=custom_api))
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
            "gdc_vmruntime_assets._import_kubernetes_modules",
            return_value=(None, fake_client_module, None, fake_api_exception),
        ),
        patch("gdc_vmruntime_assets._wait_for_vm_stopped") as mock_wait_stopped,
    ):
        run_power_operation(
            "stop",
            {
                "gdc_namespace": "range-42",
                "gdc_vm_name": "range-42-victims-victim-1234",
            },
        )

    command = mock_run.call_args.args[0]
    assert command[0] == "kubectl"
    assert "virt" in command
    assert "stop" in command
    assert "range-42-victims-victim-1234" in command
    assert "range-42" in command
    mock_wait_stopped.assert_called_once_with(
        custom_api,
        "range-42",
        "range-42-victims-victim-1234",
        fake_api_exception,
    )
