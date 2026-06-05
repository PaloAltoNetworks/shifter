"""GDC VirtualMachine and VirtualMachineDisk manifest builders + labels.

Pure-data helpers that translate Shifter scenario inputs and resolved
secrets/IPs into the custom-resource bodies passed to the GDC API.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from _gdc_vm_image_source import _resolve_image_source
from _gdc_vm_kube import _VM_GROUP, _VM_VERSION
from _gdc_vm_naming import _sanitize_name

_MANAGED_BY_LABEL = "shifter-provisioner"


def _asset_labels(range_id: int, request_uuid: str, subnet_name: str, instance_uuid: str) -> dict[str, str]:
    """Return the standard Shifter labels applied to GDC asset resources."""
    labels = {
        "app.kubernetes.io/managed-by": _MANAGED_BY_LABEL,
        "shifter.dev/range-id": str(range_id),
        "shifter.dev/request-id": request_uuid,
        "shifter.dev/subnet-name": _sanitize_name(subnet_name),
        "shifter.dev/range-plane": "gdc-vmruntime",
    }
    if instance_uuid:
        labels["shifter.dev/instance-uuid"] = instance_uuid
    return labels


def _build_disk_manifest(
    *,
    namespace: str,
    disk_name: str,
    source_url: str,
    gcs_secret_name: str | None,
    disk_size_gib: int,
    storage_class_name: str,
    labels: dict[str, str],
) -> dict[str, Any]:
    """Build the ``VirtualMachineDisk`` custom resource manifest."""
    return {
        "apiVersion": f"{_VM_GROUP}/{_VM_VERSION}",
        "kind": "VirtualMachineDisk",
        "metadata": {
            "name": disk_name,
            "namespace": namespace,
            "labels": labels,
        },
        "spec": {
            "size": f"{disk_size_gib}Gi",
            "storageClassName": storage_class_name,
            "source": _resolve_image_source(source_url, gcs_secret_name),
        },
    }


@dataclass(frozen=True)
class _VMNetworkSpec:
    """Network attachment inputs for a GDC VirtualMachine manifest."""

    network_name: str
    static_ip: str
    subnet_cidr: str


@dataclass(frozen=True)
class _VMComputeSpec:
    """Compute / OS sizing inputs for a GDC VirtualMachine manifest."""

    os_label: str
    vcpus: int
    memory: str


def _build_vm_manifest(
    *,
    namespace: str,
    vm_name: str,
    disk_name: str,
    user_data: str,
    labels: dict[str, str],
    network: _VMNetworkSpec,
    compute: _VMComputeSpec,
) -> dict[str, Any]:
    """Build the ``VirtualMachine`` custom resource manifest."""
    prefix_length = network.subnet_cidr.split("/", 1)[1]
    return {
        "apiVersion": f"{_VM_GROUP}/{_VM_VERSION}",
        "kind": "VirtualMachine",
        "metadata": {
            "name": vm_name,
            "namespace": namespace,
            "labels": labels,
        },
        "spec": {
            "osType": compute.os_label,
            "compute": {
                "cpu": {"vcpus": compute.vcpus},
                "memory": {"capacity": compute.memory},
            },
            "interfaces": [
                {
                    "name": "eth0",
                    "networkName": network.network_name,
                    "ipAddresses": [f"{network.static_ip}/{prefix_length}"],
                    "default": True,
                }
            ],
            "disks": [
                {
                    "boot": True,
                    "autoDelete": False,
                    "virtualMachineDiskName": disk_name,
                }
            ],
            "cloudInit": {
                "noCloud": {
                    "userData": user_data,
                }
            },
        },
    }
