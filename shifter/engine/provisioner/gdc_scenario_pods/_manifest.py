"""Pod naming, labeling, and manifest construction for GDC scenario Pods."""

from __future__ import annotations

import json
import re
from typing import Any

_MANAGED_BY_LABEL = "shifter-provisioner"
_NETWORKS_ANNOTATION = "k8s.v1.cni.cncf.io/networks"


def _sanitize_name(value: str, *, max_length: int = 63) -> str:
    """Lowercase, hyphenate, and truncate ``value`` into a DNS-1123-safe name."""
    normalized = re.sub(r"[^a-z0-9-]+", "-", value.strip().lower())
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    normalized = normalized[:max_length].rstrip("-")
    return normalized or "range"


def _assignment_key(instance: dict[str, Any], index: int) -> str:
    """Build the stable key used by the network runner for per-asset IPs."""
    uuid_value = str(instance.get("uuid", "")).strip()
    if uuid_value:
        return uuid_value
    name_value = str(instance.get("name", "")).strip()
    if name_value:
        return name_value
    return f"asset-{index}"


def _is_scenario_pod(instance: dict[str, Any]) -> bool:
    """Return True when the instance should be provisioned as a scenario Pod."""
    return str(instance.get("asset_type", "vm_runtime_vm")).strip() == "scenario_pod"


def _pod_name(range_id: int, subnet_name: str, instance: dict[str, Any]) -> str:
    """Build the sanitized scenario Pod name for an instance in a subnet."""
    uuid_value = str(instance.get("uuid", "")).strip()
    token = uuid_value.split("-")[-1] if uuid_value else str(instance.get("name", "pod"))
    role = str(instance.get("role", "pod")).strip()
    return _sanitize_name(f"range-{range_id}-{subnet_name}-{role}-{token}-pod")


def _pod_labels(range_id: int, request_uuid: str, subnet_name: str, instance_uuid: str) -> dict[str, str]:
    """Build the standard Kubernetes labels for a scenario Pod."""
    labels = {
        "app.kubernetes.io/managed-by": _MANAGED_BY_LABEL,
        "shifter.dev/range-id": str(range_id),
        "shifter.dev/request-id": request_uuid,
        "shifter.dev/subnet-name": _sanitize_name(subnet_name),
        "shifter.dev/range-plane": "gdc-vmruntime",
        "shifter.dev/asset-type": "scenario-pod",
    }
    if instance_uuid:
        labels["shifter.dev/instance-uuid"] = instance_uuid
    return labels


def _build_networks_annotation(network_name: str, static_ip: str) -> str:
    """Build the Multus ``k8s.v1.cni.cncf.io/networks`` annotation JSON for a static-IP attachment."""
    return json.dumps(
        [
            {
                "name": network_name,
                "interface": "net1",
                "ips": [static_ip],
            }
        ]
    )


def _build_pod_manifest(
    # Moved private helper; already keyword-only, parameter-object refactor out of scope for a decomposition.
    *,  # NOSONAR
    namespace: str,
    pod_name: str,
    hostname: str,
    network_name: str,
    static_ip: str,
    image: str,
    image_pull_policy: str,
    labels: dict[str, str],
) -> dict[str, Any]:
    """Build the Kubernetes Pod manifest dict for a GDC scenario-Pod asset."""
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": pod_name,
            "namespace": namespace,
            "labels": labels,
            "annotations": {
                _NETWORKS_ANNOTATION: _build_networks_annotation(network_name, static_ip),
            },
        },
        "spec": {
            "hostname": hostname,
            "enableServiceLinks": False,
            "restartPolicy": "Always",
            "containers": [
                {
                    "name": "scenario-asset",
                    "image": image,
                    "imagePullPolicy": image_pull_policy,
                    "command": ["/bin/sh", "-c"],
                    "args": ["trap : TERM INT; while true; do sleep 3600; done"],
                }
            ],
        },
    }


def _get_runtime_metadata(state: dict[str, Any]) -> dict[str, Any]:
    """Return the GCP/GDC provider metadata block from a range-network state payload."""
    provider_metadata = state.get("provider_metadata")
    if not isinstance(provider_metadata, dict):
        return {}

    for key in ("gcp", "gdc"):
        metadata = provider_metadata.get(key)
        if isinstance(metadata, dict):
            return metadata
    return {}


def _first_non_empty_str(*candidates: object) -> str:
    """Return the first stringifiable non-empty (after strip) candidate, or ''."""
    for candidate in candidates:
        if candidate is None:
            continue
        value = str(candidate).strip()
        if value:
            return value
    return ""


def _build_subnet_pod_context(
    *,
    subnet: dict[str, Any],
    subnet_outputs: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any], dict[str, Any], str, str]:
    """Resolve a subnet's name, output, IP assignments, namespace, and network name for scenario Pods."""
    subnet_name = str(subnet.get("name", "")).strip()
    subnet_output = subnet_outputs.get(subnet_name, {})
    network_name = str(subnet_output.get("gdc_nad_name") or subnet_output.get("gdc_network_name") or "").strip()
    namespace = str(subnet_output.get("gdc_namespace", "")).strip()
    asset_ip_assignments = dict(subnet_output.get("gdc_asset_ip_assignments") or {})
    if not subnet_name or not namespace or not network_name:
        raise RuntimeError(f"GDC subnet output missing scenario Pod network details for {subnet_name!r}")
    return subnet_name, subnet_output, asset_ip_assignments, namespace, network_name
