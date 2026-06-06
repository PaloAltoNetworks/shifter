"""Tests for the gdc_vmseries_common naming/label helpers.

These pure helpers produce the deterministic Kubernetes / Secret-Manager
resource names for VM-Series instances. The apply_ngfw path mocks the secret
and k8s calls, so several of these are not exercised there; cover them directly.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from gdc_vmseries_common import (
    _boot_disk_name,
    _bootstrap_disk_name,
    _labels,
    _namespace_name,
    _resource_prefix,
    _ssh_secret_id,
    _vm_name,
)


class _Cfg:
    namespace_prefix = "ngfw"


def test_namespace_name_includes_prefix_and_user() -> None:
    name = _namespace_name(_Cfg(), 42)
    assert "ngfw" in name
    assert "user-42" in name


def test_resource_prefix_is_deterministic_and_vm_name_matches() -> None:
    prefix = _resource_prefix(42, "abcdef12-3456-7890")
    assert prefix.startswith("ngfw-user-42-")
    # _vm_name is the resource prefix for the same inputs.
    assert _vm_name(42, "abcdef12-3456-7890") == prefix


def test_disk_names_derive_from_vm_name() -> None:
    assert _boot_disk_name("ngfw-user-42-abcdef") == "ngfw-user-42-abcdef-boot"
    assert _bootstrap_disk_name("ngfw-user-42-abcdef") == "ngfw-user-42-abcdef-bootstrap"


def test_ssh_secret_id_includes_user_and_ssh_suffix() -> None:
    secret_id = _ssh_secret_id(42, "abcdef12-3456")
    assert "ngfw-user-42" in secret_id
    assert secret_id.endswith("-ssh")


def test_labels_carry_managed_by_product_and_identity() -> None:
    labels = _labels(user_id=42, request_id="req-1", instance_id="inst-1")
    assert labels["app.kubernetes.io/managed-by"] == "shifter-provisioner"
    assert labels["shifter.dev/product"] == "palo-alto-vm-series"
    assert labels["shifter.dev/user-id"] == "42"
    assert labels["shifter.dev/request-id"] == "req-1"
    assert labels["shifter.dev/instance-uuid"] == "inst-1"
