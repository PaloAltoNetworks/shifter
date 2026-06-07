"""Shared constants and naming helpers for the GDC VM-Series NGFW lifecycle.

Extracted from ``gdc_vmseries_ngfw.py`` (Sonar S104). Holds the label/product
constants, the ``_VMSeriesNames`` projection, and the deterministic
Kubernetes/Secret-Manager resource-name helpers used by both the asset
builders (``gdc_vmseries_assets``) and the lifecycle orchestration
(``gdc_vmseries_ngfw``). This module depends only on the low-level
``gdc_vmruntime_assets`` sanitizer, so it sits at the bottom of the import
graph with no cycle back to its consumers.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, NamedTuple

from gdc_vmruntime_assets import _sanitize_name

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from config import GDCPaloAltoVMSeriesConfig

_MANAGED_BY_LABEL = "shifter-provisioner"
_ATTACHMENT_MODE = "gdc-vmruntime-palo-alto-vmseries"
_PRODUCT = "palo-alto-vm-series"
_MGMT_INTERFACE_NAME = "eth0"
_DATA_INTERFACE_NAME = "eth1"
_SECRETMANAGER_MODULE = "google.cloud.secretmanager"
_GOOGLE_EXCEPTIONS_MODULE = "google.api_core.exceptions"
_INIT_CFG_FILENAME = "init-cfg.txt"
_BOOTSTRAP_XML_FILENAME = "bootstrap.xml"
_KEEP_FILENAME = ".keep"
_GCS_PREFIX = "gs://"


class _VMSeriesNames(NamedTuple):
    """The Kubernetes resource names for one VM-Series instance."""

    namespace: str
    vm_name: str
    boot_disk_name: str
    bootstrap_disk_name: str


def _namespace_name(config: GDCPaloAltoVMSeriesConfig, user_id: int) -> str:
    """Return the per-user GDC namespace for the VM-Series range plane."""
    return _sanitize_name(f"{config.namespace_prefix}-user-{user_id}")


def _resource_prefix(user_id: int, instance_id: str) -> str:
    """Return the shared name prefix for a user's VM-Series Kubernetes resources."""
    instance_token = _sanitize_name(str(instance_id).split("-")[0], max_length=12)
    return _sanitize_name(f"ngfw-user-{user_id}-{instance_token}")


def _vm_name(user_id: int, instance_id: str) -> str:
    """Return the VirtualMachine resource name for the given user/instance."""
    return _resource_prefix(user_id, instance_id)


def _boot_disk_name(vm_name: str) -> str:
    """Return the boot-disk resource name derived from a VM name."""
    return _sanitize_name(f"{vm_name}-boot")


def _bootstrap_disk_name(vm_name: str) -> str:
    """Return the bootstrap-disk resource name derived from a VM name."""
    return _sanitize_name(f"{vm_name}-bootstrap")


def _ssh_secret_id(user_id: int, instance_id: str) -> str:
    """Return the Secret Manager secret id holding the VM-Series SSH key."""
    environment = _sanitize_name(os.environ.get("ENVIRONMENT", "gcp-dev"), max_length=32)
    instance_token = str(instance_id).split("-")[0]
    return _sanitize_name(f"shifter-{environment}-ngfw-user-{user_id}-{instance_token}-ssh", max_length=255)


def _labels(*, user_id: int, request_id: str, instance_id: str) -> dict[str, str]:
    """Return the standard Kubernetes labels applied to VM-Series resources."""
    return {
        "app.kubernetes.io/managed-by": _MANAGED_BY_LABEL,
        "shifter.dev/component": "ngfw",
        "shifter.dev/product": _PRODUCT,
        "shifter.dev/range-plane": "gdc-vmruntime",
        "shifter.dev/user-id": str(user_id),
        "shifter.dev/request-id": str(request_id),
        "shifter.dev/instance-uuid": str(instance_id),
    }


def contextlib_suppress(*exceptions: type[BaseException]) -> AbstractContextManager[None]:
    """Small wrapper to keep suppress local without shadowing test patches."""
    import contextlib

    return contextlib.suppress(*exceptions)
