"""Binding checks for deterministic GCE participant hosts."""

from __future__ import annotations

from config import GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST
from gcp_range_cell_naming import _label_value
from gcp_range_cell_resources import HOST_PUBLIC_KEY_METADATA_KEY
from gcp_range_cell_types import InstancePlan, RangeCellPlan


class GCEInstanceBindingError(RuntimeError):
    """An existing deterministic VM does not belong to this range profile."""


def _host_public_key_from_instance(existing: object) -> str:
    """Recover the provisioner-issued host key instead of minting a mismatched one."""
    metadata = getattr(existing, "metadata", None)
    for item in getattr(metadata, "items", None) or []:
        if getattr(item, "key", None) == HOST_PUBLIC_KEY_METADATA_KEY:
            return str(getattr(item, "value", "") or "")
    return ""


def _existing_label(existing: object, key: str) -> str:
    """Read one label from a dict-like Compute instance response."""
    labels = getattr(existing, "labels", None)
    getter = getattr(labels, "get", None)
    if callable(getter):
        return str(getter(key, "") or "")
    return ""


def _assert_instance_image_binding(existing: object, instance: InstancePlan) -> None:
    """Reject a keyed deterministic VM whose recorded profile differs from the plan."""
    expected_key = instance["image_key"]
    if not expected_key:
        return
    actual_key = _existing_label(existing, "image-key")
    actual_profile = _existing_label(existing, "image-profile")
    if actual_key != expected_key or actual_profile != instance["image_profile_fingerprint"]:
        raise RuntimeError(
            "Existing GCE range instance has an image-profile binding that differs from the current plan; "
            f"ami_key={expected_key!r}. Recreate the range instead of reusing the drifted instance."
        )


def _assert_preconfigured_host_binding(existing: object, plan: RangeCellPlan, instance: InstancePlan) -> None:
    """Never adopt a participant host with different ownership or image policy."""
    if instance["profile"].bootstrap_capability != GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST:
        return
    expected = {
        "managed-by": plan["labels"]["managed-by"],
        "range-id": plan["labels"]["range-id"],
        "image-key": _label_value(instance["image_key"] or "default"),
        "image-profile": instance["image_profile_fingerprint"],
    }
    if any(_existing_label(existing, key) != value for key, value in expected.items()):
        raise GCEInstanceBindingError("Existing GCE participant host has a conflicting range or image-profile binding")
