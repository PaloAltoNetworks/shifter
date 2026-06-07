"""Tests for Palo Alto VM-Series lifecycle on GDC VM Runtime."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import GDCNetworkAccessConfig, GDCPaloAltoVMSeriesConfig
from gdc_vmseries_assets import (
    _build_bootstrap_disk_manifest,
    _build_init_cfg,
    _build_vmseries_vm_manifest,
)
from gdc_vmseries_ngfw import (
    apply_ngfw,
    run_power_operation,
)


def _access_config() -> GDCNetworkAccessConfig:
    return GDCNetworkAccessConfig(
        access_secret_id="projects/test/secrets/gdc-access",
        kubeconfig="apiVersion: v1\nclusters: []\ncontexts: []\ncurrent-context: ''\nusers: []\n",
        cluster_id="cluster1",
        vxlan_cidr="10.200.0.0/24",
        region="us-central1",
    )


def _vmseries_config() -> GDCPaloAltoVMSeriesConfig:
    return GDCPaloAltoVMSeriesConfig(
        image_url="gs://images/panos-vmseries.qcow2",
        bootstrap_bucket="shifter-gcp-dev-vmseries-bootstrap",
        image_gcs_secret_id="projects/test/secrets/gcs-import",
        management_network_name="pod-network",
        management_ip_cidr="10.200.0.20/24",
        data_network_name="ngfw-data",
        data_ip_cidr="10.200.1.10/24",
        route_next_hop_ip="10.200.1.1",
        vcpus=8,
        memory="16Gi",
        disk_size_gib=100,
    )


def test_build_init_cfg_keeps_existing_vmseries_bootstrap_contract():
    init_cfg = _build_init_cfg(
        hostname="ngfw-user-42",
        app_spec={
            "scm_pin_id": "pin-id",
            "scm_pin_value": "pin-value",
            "scm_folder_name": "tenant-folder",
        },
    )

    assert "type=dhcp-client" in init_cfg
    assert "hostname=ngfw-user-42" in init_cfg
    assert "panorama-server=cloud" in init_cfg
    assert "vm-series-auto-registration-pin-id=pin-id" in init_cfg
    assert "vm-series-auto-registration-pin-value=pin-value" in init_cfg
    assert "dgname=tenant-folder" in init_cfg


def test_build_bootstrap_disk_manifest_uses_cdrom_disk_type():
    manifest = _build_bootstrap_disk_manifest(
        namespace="ngfw-user-42",
        disk_name="ngfw-bootstrap",
        source_url="gs://bucket/bootstrap.iso",
        gcs_secret_name="gcs-import",
        disk_size_gib=1,
        storage_class_name="local-shared",
        labels={"shifter.dev/component": "ngfw"},
    )

    assert manifest["kind"] == "VirtualMachineDisk"
    assert manifest["spec"]["diskType"] == "cdrom"
    assert manifest["spec"]["source"]["gcs"]["url"] == "gs://bucket/bootstrap.iso"
    assert manifest["spec"]["source"]["gcs"]["secretRef"] == "gcs-import"


def test_build_vmseries_vm_manifest_uses_management_and_data_interfaces():
    manifest = _build_vmseries_vm_manifest(
        namespace="ngfw-user-42",
        vm_name="ngfw-user-42-abcdef",
        boot_disk_name="ngfw-user-42-abcdef-boot",
        bootstrap_disk_name="ngfw-user-42-abcdef-bootstrap",
        config=_vmseries_config(),
        labels={"shifter.dev/component": "ngfw"},
    )

    assert manifest["kind"] == "VirtualMachine"
    assert manifest["spec"]["interfaces"] == [
        {
            "name": "eth0",
            "networkName": "pod-network",
            "default": True,
            "ipAddresses": ["10.200.0.20/24"],
        },
        {
            "name": "eth1",
            "networkName": "ngfw-data",
            "default": False,
            "ipAddresses": ["10.200.1.10/24"],
        },
    ]
    assert manifest["spec"]["disks"][1]["virtualMachineDiskName"] == "ngfw-user-42-abcdef-bootstrap"


@patch("gdc_vmseries_ngfw._wait_for_vm_ready")
@patch("gdc_vmseries_ngfw._wait_for_disk_ready")
@patch("gdc_vmseries_ngfw._apply_namespaced_custom_object")
@patch("gdc_vmseries_ngfw._create_bootstrap_iso", return_value="gs://bootstrap/ngfw/bootstrap.iso")
@patch("gdc_vmseries_ngfw._ensure_ssh_secret", return_value=("projects/test/secrets/ngfw-ssh", "ssh-rsa test"))
@patch("gdc_vmseries_ngfw._ensure_gcs_image_secret", return_value="gcs-import")
@patch("gdc_vmseries_ngfw._build_kube_api_client", return_value=object())
@patch("gdc_vmseries_ngfw._import_kubernetes_modules")
@patch("gdc_vmseries_ngfw.load_gdc_palo_alto_vmseries_config", return_value=_vmseries_config())
@patch("gdc_vmseries_ngfw.load_gdc_network_access_config", return_value=_access_config())
def test_apply_ngfw_creates_palo_alto_vmseries_gdc_state(
    _mock_access,
    _mock_config,
    mock_import,
    _mock_api_client,
    _mock_gcs_secret,
    _mock_ssh_secret,
    _mock_bootstrap_iso,
    mock_apply,
    _mock_disk_ready,
    mock_vm_ready,
):
    client_module = MagicMock()
    api_exception = type("ApiException", (Exception,), {"status": 404})
    mock_import.return_value = (None, client_module, None, api_exception)
    mock_vm_ready.return_value = {
        "status": {
            "state": "running",
            "interfaces": [
                {"name": "eth0", "ipAddresses": ["10.200.0.20/24"]},
                {"name": "eth1", "ipAddresses": ["10.200.1.10/24"]},
            ],
        }
    }

    output = apply_ngfw(
        request_id="req-123",
        instance_id="abcdef12-3456-7890-abcd-ef1234567890",
        app_spec={"user_id": 42, "scm_pin_id": "pin-id", "authcode": "auth"},
    )

    applied_kinds = [call.kwargs["body"]["kind"] for call in mock_apply.call_args_list]
    assert applied_kinds == ["VirtualMachineDisk", "VirtualMachineDisk", "VirtualMachine"]
    assert output["cloud_provider"] == "gcp"
    assert output["product"] == "palo-alto-vm-series"
    assert output["management_ip"] == "10.200.0.20"
    assert output["dataplane_ip"] == "10.200.1.10"
    assert output["route_next_hop_ip"] == "10.200.1.1"
    assert output["attachment_mode"] == "gdc-vmruntime-palo-alto-vmseries"
    assert output["provider_metadata"]["gcp"]["product"] == "palo-alto-vm-series"
    assert output["provider_metadata"]["gcp"]["data_attachment_id"].endswith(":eth1")


@patch("gdc_vmseries_ngfw.subprocess.run")
@patch("gdc_vmseries_ngfw.load_gdc_network_access_config", return_value=_access_config())
def test_run_power_operation_uses_kubectl_virt(mock_access, mock_run):
    state = {
        "provider_metadata": {
            "gcp": {
                "namespace": "ngfw-user-42",
                "vm_name": "ngfw-user-42-abcdef",
            }
        }
    }

    run_power_operation("stop", state)

    command = mock_run.call_args.args[0]
    assert command[0] == "kubectl"
    assert "virt" in command
    assert "stop" in command
    assert "ngfw-user-42-abcdef" in command
    assert "ngfw-user-42" in command
    assert mock_access.called
