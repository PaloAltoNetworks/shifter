"""Orchestration helpers for the GDC VM Runtime asset entry points.

Pure-data classification helpers, subnet/context builders, power-target
resolution, and asset iteration for ``apply_range_assets`` /
``destroy_range_assets`` / ``run_power_operation``.

Functions that call into patched-by-tests names (``_ensure_ssh_secret``,
``_delete_ssh_secret``, ``_wait_for_*``, ``_apply_namespaced_custom_object``,
``_collect_vmi_metadata`` etc.) stay in ``gdc_vmruntime_assets`` itself
so existing test patches keep working against the historical
``gdc_vmruntime_assets.X`` namespace.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from _gdc_vm_naming import _sanitize_name
from config import GDCNetworkAccessConfig, GDCVMRuntimeConfig


@dataclass(frozen=True)
class _KubeAccess:
    """Bundle the kubernetes API handle and ApiException type for a runner call."""

    custom_api: Any
    api_exception: Any


@dataclass(frozen=True)
class _SubnetContext:
    """Per-subnet network details needed to build VM Runtime resources."""

    namespace: str
    subnet_name: str
    subnet_cidr: str
    network_name: str
    asset_ip_assignments: dict[str, Any]


def _is_vm_runtime_asset(instance: dict[str, Any]) -> bool:
    """Return True when the instance should be provisioned as a VM Runtime VM."""
    return str(instance.get("asset_type", "vm_runtime_vm")).strip() == "vm_runtime_vm"


def _get_runtime_metadata(state: dict[str, Any]) -> dict[str, Any]:
    """Return the GCP/GDC provider_metadata block for an instance state."""
    provider_metadata = state.get("provider_metadata")
    if not isinstance(provider_metadata, dict):
        return {}

    for provider_name in ("gcp", "gdc"):
        metadata = provider_metadata.get(provider_name)
        if isinstance(metadata, dict):
            return metadata

    return {}


def _resolve_power_target(state: dict[str, Any]) -> tuple[str, str]:
    """Return the ``(namespace, vm_name)`` target for a power operation."""
    metadata = _get_runtime_metadata(state)
    namespace = str(metadata.get("namespace") or state.get("gdc_namespace", "")).strip()
    vm_name = str(metadata.get("vm_name") or state.get("gdc_vm_name") or state.get("instance_id", "")).strip()
    if not namespace or not vm_name:
        raise RuntimeError("GDC VM Runtime state is missing namespace or VM name")
    return namespace, vm_name


def _instance_os_label(os_type: str) -> str:
    """Return the GDC ``osType`` label for an instance's OS."""
    return "Windows" if os_type == "windows" else "Linux"


def _select_namespace(range_id: int, subnet_outputs: dict[str, dict[str, Any]], access: GDCNetworkAccessConfig) -> str:
    """Return the GDC namespace to provision VM assets into."""
    for subnet_output in subnet_outputs.values():
        namespace = str(subnet_output.get("gdc_namespace", "")).strip()
        if namespace:
            return namespace
    return _sanitize_name(f"{access.namespace_prefix}-{range_id}")


def _iter_vm_runtime_instances(subnets: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """Return ``(subnet_name, instance)`` pairs for every VM Runtime asset across subnets."""
    assets: list[tuple[str, dict[str, Any]]] = []
    for subnet in subnets:
        subnet_name = str(subnet.get("name", "")).strip()
        for instance in subnet.get("instances") or []:
            if _is_vm_runtime_asset(instance):
                assets.append((subnet_name, instance))
    return assets


def _build_subnet_context(subnet: dict[str, Any], subnet_outputs: dict[str, dict[str, Any]]) -> _SubnetContext:
    """Build a ``_SubnetContext`` from a scenario subnet plus its network output."""
    subnet_name = str(subnet.get("name", "")).strip()
    subnet_output = subnet_outputs.get(subnet_name, {})
    subnet_cidr = str(subnet_output.get("subnet_cidr", "")).strip()
    network_name = str(subnet_output.get("gdc_network_name", "")).strip()
    if not subnet_name or not subnet_cidr or not network_name:
        raise RuntimeError(f"GDC subnet output missing network details for {subnet_name!r}")
    return _SubnetContext(
        namespace="",
        subnet_name=subnet_name,
        subnet_cidr=subnet_cidr,
        network_name=network_name,
        asset_ip_assignments=dict(subnet_output.get("gdc_asset_ip_assignments") or {}),
    )


def _build_subnet_pending_instances(
    *,
    subnet: dict[str, Any],
    subnet_outputs: dict[str, dict[str, Any]],
    namespace: str,
    range_id: int,
    request_uuid: str,
    vm_config: GDCVMRuntimeConfig,
    gcs_secret_name: str | None,
    kube: _KubeAccess,
    build_instance: Callable[..., dict[str, Any]],
) -> list[dict[str, Any]]:
    """Apply VM Runtime manifests for every asset in ``subnet`` and return pending records.

    ``build_instance`` is injected (rather than imported) so that calls
    into ``_build_pending_vm_runtime_instance`` continue to resolve via
    ``gdc_vmruntime_assets``'s namespace, preserving the existing test
    patches on its dependency helpers.
    """
    base_context = _build_subnet_context(subnet, subnet_outputs)
    context = _SubnetContext(
        namespace=namespace,
        subnet_name=base_context.subnet_name,
        subnet_cidr=base_context.subnet_cidr,
        network_name=base_context.network_name,
        asset_ip_assignments=base_context.asset_ip_assignments,
    )
    subnet_output = subnet_outputs.get(base_context.subnet_name, {})
    pending: list[dict[str, Any]] = []
    for index, instance in enumerate(list(subnet.get("instances") or [])):
        if not _is_vm_runtime_asset(instance):
            continue
        pending.append(
            {
                **build_instance(
                    range_id=range_id,
                    request_uuid=request_uuid,
                    instance=instance,
                    index=index,
                    subnet=context,
                    vm_config=vm_config,
                    gcs_secret_name=gcs_secret_name,
                    kube=kube,
                ),
                "subnet_output": subnet_output,
            }
        )
    return pending
