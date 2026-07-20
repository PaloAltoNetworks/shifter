"""DNS/Kubernetes-safe naming helpers for GDC VM Runtime assets.

Pure-function helpers that derive sanitized resource names, instance
tokens, assignment keys, and per-instance secret IDs from the scenario
instance dicts the provisioner sees. No GCP or kubernetes imports.
"""

from __future__ import annotations

import os
import re
from typing import Any

from components.instance import sanitize_hostname


def _sanitize_name(value: str, *, max_length: int = 63) -> str:
    """Return a DNS/Kubernetes-safe name derived from ``value``."""
    normalized = re.sub(r"[^a-z0-9-]+", "-", value.strip().lower())
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    normalized = normalized[:max_length].rstrip("-")
    return normalized or "range"


def _instance_token(instance: dict[str, Any]) -> str:
    """Return a short stable token derived from the instance identity."""
    uuid_value = str(instance.get("uuid", "")).strip()
    if uuid_value:
        return _sanitize_name(uuid_value.split("-")[-1], max_length=12)
    name_value = str(instance.get("name", "")).strip()
    if name_value:
        return _sanitize_name(name_value, max_length=12)
    return _sanitize_name(f"{instance.get('role', 'vm')}-{instance.get('os_type', 'guest')}", max_length=12)


def _assignment_key(instance: dict[str, Any], index: int) -> str:
    """Build the stable key used by the network runner for per-asset IPs."""
    uuid_value = str(instance.get("uuid", "")).strip()
    if uuid_value:
        return uuid_value
    name_value = str(instance.get("name", "")).strip()
    if name_value:
        return name_value
    return f"asset-{index}"


def _vm_name(range_id: int, subnet_name: str, instance: dict[str, Any]) -> str:
    """Return the GDC VirtualMachine resource name for an instance."""
    token = _instance_token(instance)
    role = _sanitize_name(str(instance.get("role", "vm")), max_length=12)
    return _sanitize_name(f"range-{range_id}-{subnet_name}-{role}-{token}")


def _disk_name(vm_name: str) -> str:
    """Return the GDC VirtualMachineDisk name for a given VM."""
    return _sanitize_name(f"{vm_name}-boot")


def _build_instance_hostname(instance: dict[str, Any], vm_name: str) -> str:
    """Return the guest hostname for an instance, falling back to the VM name."""
    display_name = str(instance.get("name", "")).strip()
    if display_name:
        return sanitize_hostname(display_name)
    return sanitize_hostname(vm_name, max_length=20)


def _build_instance_secret_name(range_id: int, instance: dict[str, Any], *, kind: str = "ssh") -> str:
    """Build a per-instance Secret Manager secret name for ``kind``.

    ``kind`` is appended as the trailing identifier so SSH keys and RDP
    passwords live in distinct secrets per instance (``ssh`` vs
    ``rdp-password``). The naming pattern matches the AWS Terraform
    range module convention.
    """
    environment = _sanitize_name(os.environ.get("ENVIRONMENT", "gcp-dev"), max_length=32)
    token = _instance_token(instance)
    role = _sanitize_name(str(instance.get("role", "vm")), max_length=12)
    return _sanitize_name(
        f"shifter-{environment}-range-{range_id}-{role}-{token}-{kind}",
        max_length=255,
    )
