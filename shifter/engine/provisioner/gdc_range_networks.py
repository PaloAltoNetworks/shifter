"""GDC custom L2 scenario network provisioning for the active GCP range plane."""

from __future__ import annotations

import ipaddress
import json
import logging
import re
from typing import Any

import yaml

from config import GDCNetworkAccessConfig, load_gdc_network_access_config

logger = logging.getLogger(__name__)

_NETWORK_GROUP = "networking.gke.io"
_NETWORK_VERSION = "v1"
_NETWORK_PLURAL = "networks"
_NAD_GROUP = "k8s.cni.cncf.io"
_NAD_VERSION = "v1"
_NAD_PLURAL = "network-attachment-definitions"
_MANAGED_BY_LABEL = "shifter-provisioner"


def _import_kubernetes_modules():
    try:
        import kubernetes
        from kubernetes import client, config
        from kubernetes.client.exceptions import ApiException
    except ImportError as exc:
        raise RuntimeError("GDC range networking requires the kubernetes Python client") from exc

    return kubernetes, client, config, ApiException


def _sanitize_name(value: str, *, max_length: int = 63) -> str:
    normalized = re.sub(r"[^a-z0-9-]+", "-", value.strip().lower())
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    normalized = normalized[:max_length].rstrip("-")
    return normalized or "range"


def _range_namespace_name(config: GDCNetworkAccessConfig, range_id: int) -> str:
    return _sanitize_name(f"{config.namespace_prefix}-{range_id}")


def _network_name(range_id: int, subnet_name: str) -> str:
    return _sanitize_name(f"range-{range_id}-{subnet_name}")


def _network_labels(range_id: int, request_uuid: str, subnet_name: str) -> dict[str, str]:
    return {
        "app.kubernetes.io/managed-by": _MANAGED_BY_LABEL,
        "shifter.dev/range-id": str(range_id),
        "shifter.dev/request-id": request_uuid,
        "shifter.dev/subnet-name": _sanitize_name(subnet_name),
        "shifter.dev/range-plane": "gdc-vmruntime",
    }


def _build_kube_api_client(kubeconfig_yaml: str):
    _, client, config, _ = _import_kubernetes_modules()

    kubeconfig_dict = yaml.safe_load(kubeconfig_yaml)
    if not isinstance(kubeconfig_dict, dict):
        raise RuntimeError("GDC kubeconfig secret did not decode into a kubeconfig document")

    loader = config.kube_config.KubeConfigLoader(config_dict=kubeconfig_dict)
    configuration = client.Configuration()
    loader.load_and_set(configuration)
    return client.ApiClient(configuration=configuration)


def _compute_network_allocation(
    cidr: str,
    *,
    static_ip_reservation_count: int,
) -> tuple[str, list[str], list[str]]:
    network = ipaddress.ip_network(cidr)
    if not isinstance(network, ipaddress.IPv4Network):
        raise RuntimeError(f"GDC scenario networks must be IPv4, got {cidr}")

    usable_hosts = list(network.hosts())
    required_reserved = static_ip_reservation_count + 1  # gateway + static reservations
    if len(usable_hosts) <= required_reserved:
        raise RuntimeError(
            f"Subnet {cidr} is too small for {static_ip_reservation_count} reserved static IPs plus a gateway"
        )

    gateway_ip = str(usable_hosts[-1])
    static_ips = [str(ip) for ip in usable_hosts[-(required_reserved):-1]]
    exclude = [f"{ip}/32" for ip in [*static_ips, gateway_ip]]
    return gateway_ip, static_ips, exclude


def _asset_key(instance: dict[str, Any], index: int) -> str:
    """Build a stable lookup key for per-asset network assignments."""
    uuid_value = str(instance.get("uuid", "")).strip()
    if uuid_value:
        return uuid_value
    name_value = str(instance.get("name", "")).strip()
    if name_value:
        return name_value
    return f"asset-{index}"


def _is_scenario_pod(instance: dict[str, Any]) -> bool:
    """Return True when the range asset should be provisioned as a Pod."""
    return str(instance.get("asset_type", "vm_runtime_vm")).strip() == "scenario_pod"


def _compute_asset_ip_assignments(
    cidr: str,
    *,
    static_ip_reservation_count: int,
    instances: list[dict[str, Any]],
) -> tuple[str, list[str], list[str], dict[str, str]]:
    """Compute deterministic per-asset IP assignments for a mixed subnet.

    VM-backed assets keep their assigned IPs out of the NAD allocation pool.
    Pod-backed assets request their assigned IPs explicitly, so those IPs remain
    allocatable to Whereabouts but still deterministic for the range spec order.
    """
    required_static_ips = max(static_ip_reservation_count, len(instances))
    gateway_ip, reserved_static_ips, _ = _compute_network_allocation(
        cidr,
        static_ip_reservation_count=required_static_ips,
    )
    assigned_ips = reserved_static_ips[: len(instances)]
    extra_reserved_ips = reserved_static_ips[len(instances) :]

    assignments: dict[str, str] = {}
    exclude = [f"{ip}/32" for ip in extra_reserved_ips]
    for index, instance in enumerate(instances):
        assigned_ip = assigned_ips[index]
        assignments[_asset_key(instance, index)] = assigned_ip
        if not _is_scenario_pod(instance):
            exclude.append(f"{assigned_ip}/32")

    exclude.append(f"{gateway_ip}/32")
    return gateway_ip, reserved_static_ips, exclude, assignments


def _build_network_manifest(
    *,
    network_name: str,
    cidr: str,
    gateway_ip: str,
    labels: dict[str, str],
    access: GDCNetworkAccessConfig,
) -> dict[str, Any]:
    return {
        "apiVersion": f"{_NETWORK_GROUP}/{_NETWORK_VERSION}",
        "kind": "Network",
        "metadata": {
            "name": network_name,
            "labels": labels,
        },
        "spec": {
            "type": "L2",
            "nodeInterfaceMatcher": {
                "interfaceName": access.network_interface,
            },
            "gateway4": gateway_ip,
            "routes": [{"to": cidr}],
            "dnsConfig": {
                "nameservers": list(access.dns_nameservers),
            },
        },
    }


def _build_nad_manifest(
    *,
    namespace: str,
    network_name: str,
    cidr: str,
    exclude: list[str],
    labels: dict[str, str],
    access: GDCNetworkAccessConfig,
) -> dict[str, Any]:
    return {
        "apiVersion": f"{_NAD_GROUP}/{_NAD_VERSION}",
        "kind": "NetworkAttachmentDefinition",
        "metadata": {
            "name": network_name,
            "namespace": namespace,
            "labels": labels,
        },
        "spec": {
            "config": json.dumps(
                {
                    "cniVersion": "0.3.1",
                    "name": network_name,
                    "type": "macvlan",
                    "master": access.network_interface,
                    "mode": "bridge",
                    "ipam": {
                        "type": "whereabouts",
                        "range": cidr,
                        "exclude": exclude,
                    },
                },
                indent=2,
            ),
        },
    }


def _ensure_namespace(core_api, namespace: str, labels: dict[str, str], api_exception) -> None:
    body = {
        "metadata": {
            "name": namespace,
            "labels": labels,
        }
    }
    try:
        core_api.create_namespace(body=body)
        logger.info("Created GDC range namespace %s", namespace)
    except api_exception as exc:
        if exc.status != 409:
            raise
        core_api.patch_namespace(name=namespace, body={"metadata": {"labels": labels}})


def _apply_cluster_custom_object(custom_api, body: dict[str, Any], api_exception) -> None:
    name = body["metadata"]["name"]
    try:
        custom_api.create_cluster_custom_object(
            group=_NETWORK_GROUP,
            version=_NETWORK_VERSION,
            plural=_NETWORK_PLURAL,
            body=body,
        )
        logger.info("Created GDC Network %s", name)
    except api_exception as exc:
        if exc.status != 409:
            raise
        custom_api.patch_cluster_custom_object(
            group=_NETWORK_GROUP,
            version=_NETWORK_VERSION,
            plural=_NETWORK_PLURAL,
            name=name,
            body=body,
        )
        logger.info("Updated GDC Network %s", name)


def _apply_namespaced_custom_object(custom_api, body: dict[str, Any], namespace: str, api_exception) -> None:
    name = body["metadata"]["name"]
    try:
        custom_api.create_namespaced_custom_object(
            group=_NAD_GROUP,
            version=_NAD_VERSION,
            plural=_NAD_PLURAL,
            namespace=namespace,
            body=body,
        )
        logger.info("Created NAD %s/%s", namespace, name)
    except api_exception as exc:
        if exc.status != 409:
            raise
        custom_api.patch_namespaced_custom_object(
            group=_NAD_GROUP,
            version=_NAD_VERSION,
            plural=_NAD_PLURAL,
            namespace=namespace,
            name=name,
            body=body,
        )
        logger.info("Updated NAD %s/%s", namespace, name)


def _delete_namespaced_custom_object(custom_api, namespace: str, name: str, api_exception) -> None:
    try:
        custom_api.delete_namespaced_custom_object(
            group=_NAD_GROUP,
            version=_NAD_VERSION,
            plural=_NAD_PLURAL,
            namespace=namespace,
            name=name,
        )
        logger.info("Deleted NAD %s/%s", namespace, name)
    except api_exception as exc:
        if exc.status != 404:
            raise


def _delete_cluster_custom_object(custom_api, name: str, api_exception) -> None:
    try:
        custom_api.delete_cluster_custom_object(
            group=_NETWORK_GROUP,
            version=_NETWORK_VERSION,
            plural=_NETWORK_PLURAL,
            name=name,
        )
        logger.info("Deleted GDC Network %s", name)
    except api_exception as exc:
        if exc.status != 404:
            raise


def _delete_namespace(core_api, namespace: str, api_exception) -> None:
    try:
        core_api.delete_namespace(name=namespace)
        logger.info("Deleted GDC range namespace %s", namespace)
    except api_exception as exc:
        if exc.status != 404:
            raise


def apply_range_networks(request_uuid: str, variables: dict[str, Any]) -> dict[str, Any]:
    """Create or reconcile GDC L2 scenario networks for a range."""
    access = load_gdc_network_access_config()
    if access is None:
        raise RuntimeError("GDC range plane requires GDC_ACCESS_SECRET_ID to provision scenario networks")

    _, client, _, api_exception = _import_kubernetes_modules()
    api_client = _build_kube_api_client(access.kubeconfig)
    core_api = client.CoreV1Api(api_client)
    custom_api = client.CustomObjectsApi(api_client)

    range_id = int(variables["range_id"])
    subnets = variables.get("subnets", [])
    namespace = _range_namespace_name(access, range_id)
    _ensure_namespace(
        core_api,
        namespace,
        labels={
            "app.kubernetes.io/managed-by": _MANAGED_BY_LABEL,
            "shifter.dev/range-id": str(range_id),
            "shifter.dev/request-id": request_uuid,
        },
        api_exception=api_exception,
    )

    outputs: dict[str, dict[str, Any]] = {}
    for subnet in subnets:
        subnet_name = str(subnet.get("name", "")).strip()
        subnet_uuid = str(subnet.get("uuid", "")).strip()
        subnet_cidr = str(subnet.get("cidr", "")).strip()
        if not subnet_name or not subnet_uuid or not subnet_cidr:
            raise RuntimeError(f"GDC range network provisioning requires subnet name, uuid, and cidr: {subnet!r}")

        network_name = _network_name(range_id, subnet_name)
        labels = _network_labels(range_id, request_uuid, subnet_name)
        instances = list(subnet.get("instances") or [])
        gateway_ip, reserved_static_ips, exclude, asset_ip_assignments = _compute_asset_ip_assignments(
            subnet_cidr,
            static_ip_reservation_count=access.static_ip_reservation_count,
            instances=instances,
        )

        network_manifest = _build_network_manifest(
            network_name=network_name,
            cidr=subnet_cidr,
            gateway_ip=gateway_ip,
            labels=labels,
            access=access,
        )
        nad_manifest = _build_nad_manifest(
            namespace=namespace,
            network_name=network_name,
            cidr=subnet_cidr,
            exclude=exclude,
            labels=labels,
            access=access,
        )

        _apply_cluster_custom_object(custom_api, network_manifest, api_exception)
        _apply_namespaced_custom_object(custom_api, nad_manifest, namespace, api_exception)

        outputs[subnet_name] = {
            "uuid": subnet_uuid,
            "subnet_id": network_name,
            "subnet_cidr": subnet_cidr,
            "gdc_namespace": namespace,
            "gdc_network_name": network_name,
            "gdc_nad_name": network_name,
            "gdc_network_type": "L2",
            "gdc_node_interface": access.network_interface,
            "gdc_gateway_ip": gateway_ip,
            "gdc_ipam_range": subnet_cidr,
            "gdc_ipam_exclude": exclude,
            "gdc_reserved_static_ips": reserved_static_ips,
            "gdc_asset_ip_assignments": asset_ip_assignments,
            "gdc_cluster_id": access.cluster_id,
        }

    return {"subnets": outputs, "instances": []}


def destroy_range_networks(request_uuid: str, variables: dict[str, Any] | None) -> None:
    """Delete GDC range-plane network resources for a range."""
    if not variables:
        logger.info("No GDC range network variables provided for request %s; nothing to destroy", request_uuid)
        return

    access = load_gdc_network_access_config()
    if access is None:
        raise RuntimeError("GDC range plane requires GDC_ACCESS_SECRET_ID to destroy scenario networks")

    _, client, _, api_exception = _import_kubernetes_modules()
    api_client = _build_kube_api_client(access.kubeconfig)
    core_api = client.CoreV1Api(api_client)
    custom_api = client.CustomObjectsApi(api_client)

    range_id = int(variables["range_id"])
    namespace = _range_namespace_name(access, range_id)
    for subnet in variables.get("subnets", []):
        subnet_name = str(subnet.get("name", "")).strip()
        if not subnet_name:
            continue
        network_name = _network_name(range_id, subnet_name)
        _delete_namespaced_custom_object(custom_api, namespace, network_name, api_exception)
        _delete_cluster_custom_object(custom_api, network_name, api_exception)

    _delete_namespace(core_api, namespace, api_exception)
