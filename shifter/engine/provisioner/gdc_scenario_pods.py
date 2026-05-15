"""GDC mixed-asset scenario Pod lifecycle for shared L2 subnets."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import yaml

from config import load_gdc_network_access_config, load_gdc_scenario_pod_config

logger = logging.getLogger(__name__)

_MANAGED_BY_LABEL = "shifter-provisioner"
_NETWORKS_ANNOTATION = "k8s.v1.cni.cncf.io/networks"
_NETWORK_STATUS_ANNOTATION = "k8s.v1.cni.cncf.io/network-status"
_POLL_INTERVAL_SECONDS = 5
_READY_TIMEOUT_SECONDS = 600
_DELETE_TIMEOUT_SECONDS = 300


def _import_kubernetes_modules():
    try:
        from kubernetes import client, config
        from kubernetes.client.exceptions import ApiException
    except ImportError as exc:
        raise RuntimeError("GDC scenario Pod lifecycle requires the kubernetes Python client") from exc

    return client, config, ApiException


def _sanitize_name(value: str, *, max_length: int = 63) -> str:
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


def _build_kube_api_client(kubeconfig_yaml: str):
    client, config, _ = _import_kubernetes_modules()
    kubeconfig_dict = yaml.safe_load(kubeconfig_yaml)
    if not isinstance(kubeconfig_dict, dict):
        raise RuntimeError("GDC kubeconfig secret did not decode into a kubeconfig document")

    loader = config.kube_config.KubeConfigLoader(config_dict=kubeconfig_dict)
    configuration = client.Configuration()
    loader.load_and_set(configuration)
    return client.ApiClient(configuration=configuration)


def _pod_name(range_id: int, subnet_name: str, instance: dict[str, Any]) -> str:
    uuid_value = str(instance.get("uuid", "")).strip()
    token = uuid_value.split("-")[-1] if uuid_value else str(instance.get("name", "pod"))
    role = str(instance.get("role", "pod")).strip()
    return _sanitize_name(f"range-{range_id}-{subnet_name}-{role}-{token}-pod")


def _pod_labels(range_id: int, request_uuid: str, subnet_name: str, instance_uuid: str) -> dict[str, str]:
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
    *,
    namespace: str,
    pod_name: str,
    hostname: str,
    network_name: str,
    static_ip: str,
    image: str,
    image_pull_policy: str,
    labels: dict[str, str],
) -> dict[str, Any]:
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


def _apply_pod(core_api, namespace: str, body: dict[str, Any], api_exception) -> None:
    name = body["metadata"]["name"]
    try:
        core_api.create_namespaced_pod(namespace=namespace, body=body)
        logger.info("Created scenario Pod %s/%s", namespace, name)
    except api_exception as exc:
        if exc.status != 409:
            raise
        core_api.patch_namespaced_pod(name=name, namespace=namespace, body=body)
        logger.info("Updated scenario Pod %s/%s", namespace, name)


def _extract_network_status_ip(pod: dict[str, Any], network_name: str, namespace: str) -> str:
    annotations = pod.get("metadata", {}).get("annotations") or {}
    raw_status = annotations.get(_NETWORK_STATUS_ANNOTATION)
    if not raw_status:
        return ""

    try:
        network_status = json.loads(raw_status)
    except json.JSONDecodeError:
        return ""

    expected_names = {network_name, f"{namespace}/{network_name}"}
    for attachment in network_status:
        if not isinstance(attachment, dict):
            continue
        if attachment.get("name") not in expected_names and attachment.get("interface") != "net1":
            continue
        ips = attachment.get("ips") or []
        if ips:
            return str(ips[0]).split("/", 1)[0]
    return ""


def _wait_for_pod_ready(
    core_api,
    namespace: str,
    pod_name: str,
    expected_ip: str,
    network_name: str,
    api_exception,
) -> None:
    deadline = time.monotonic() + _READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            pod = core_api.read_namespaced_pod(name=pod_name, namespace=namespace).to_dict()
        except api_exception as exc:
            if exc.status == 404:
                time.sleep(_POLL_INTERVAL_SECONDS)
                continue
            raise

        phase = str(((pod.get("status") or {}).get("phase")) or "").lower()
        assigned_ip = _extract_network_status_ip(pod, network_name, namespace)
        if phase == "running" and assigned_ip == expected_ip:
            return
        if phase == "failed":
            raise RuntimeError(f"Scenario Pod {namespace}/{pod_name} entered phase=Failed")
        time.sleep(_POLL_INTERVAL_SECONDS)

    raise RuntimeError(f"Timed out waiting for scenario Pod {namespace}/{pod_name} to become ready")


def _wait_for_pod_deleted(core_api, namespace: str, pod_name: str, api_exception) -> None:
    deadline = time.monotonic() + _DELETE_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            core_api.read_namespaced_pod(name=pod_name, namespace=namespace)
        except api_exception as exc:
            if exc.status == 404:
                return
            raise
        time.sleep(_POLL_INTERVAL_SECONDS)

    raise RuntimeError(f"Timed out waiting for scenario Pod {namespace}/{pod_name} to delete")


def _get_runtime_metadata(state: dict[str, Any]) -> dict[str, Any]:
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


def _resolve_power_target(instance: dict[str, Any]) -> dict[str, Any]:
    raw_state = instance.get("state")
    state: dict[str, Any] = raw_state if isinstance(raw_state, dict) else {}
    metadata = _get_runtime_metadata(state)

    namespace = _first_non_empty_str(metadata.get("namespace"), state.get("gdc_namespace"))
    pod_name = _first_non_empty_str(metadata.get("pod_name"), state.get("gdc_pod_name"), state.get("instance_id"))
    network_name = _first_non_empty_str(
        metadata.get("nad_name"),
        metadata.get("network_name"),
        state.get("gdc_nad_name"),
        state.get("gdc_network_name"),
    )
    static_ip = _first_non_empty_str(metadata.get("ip"), state.get("gdc_ip"), state.get("private_ip"))
    image = _first_non_empty_str(metadata.get("container_image"), state.get("gdc_container_image"))
    subnet_name = _first_non_empty_str(state.get("subnet_name"), instance.get("subnet_name"))
    hostname = _sanitize_name(_first_non_empty_str(instance.get("name"), pod_name), max_length=63)

    if not all([namespace, pod_name, network_name, static_ip, image]):
        raise RuntimeError(
            "Scenario Pod lifecycle state is incomplete for power operation: "
            f"namespace={namespace!r} pod_name={pod_name!r} network_name={network_name!r} "
            f"static_ip={static_ip!r} image={image!r}"
        )

    labels = {
        "app.kubernetes.io/managed-by": _MANAGED_BY_LABEL,
        "shifter.dev/range-plane": "gdc-vmruntime",
        "shifter.dev/asset-type": "scenario-pod",
    }
    if subnet_name:
        labels["shifter.dev/subnet-name"] = _sanitize_name(subnet_name)
    instance_uuid = str(instance.get("uuid", "")).strip()
    if instance_uuid:
        labels["shifter.dev/instance-uuid"] = instance_uuid

    return {
        "namespace": namespace,
        "pod_name": pod_name,
        "network_name": network_name,
        "static_ip": static_ip,
        "image": image,
        "hostname": hostname,
        "labels": labels,
    }


def _build_subnet_pod_context(
    *,
    subnet: dict[str, Any],
    subnet_outputs: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any], dict[str, Any], str, str]:
    subnet_name = str(subnet.get("name", "")).strip()
    subnet_output = subnet_outputs.get(subnet_name, {})
    network_name = str(subnet_output.get("gdc_nad_name") or subnet_output.get("gdc_network_name") or "").strip()
    namespace = str(subnet_output.get("gdc_namespace", "")).strip()
    asset_ip_assignments = dict(subnet_output.get("gdc_asset_ip_assignments") or {})
    if not subnet_name or not namespace or not network_name:
        raise RuntimeError(f"GDC subnet output missing scenario Pod network details for {subnet_name!r}")
    return subnet_name, subnet_output, asset_ip_assignments, namespace, network_name


def _create_scenario_pod_asset(
    *,
    core_api,
    api_exception,
    pod_config,
    range_id: int,
    request_uuid: str,
    subnet_name: str,
    subnet_output: dict[str, Any],
    asset_ip_assignments: dict[str, Any],
    namespace: str,
    network_name: str,
    instance: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    static_ip = str(asset_ip_assignments.get(_assignment_key(instance, index), "")).strip()
    if not static_ip:
        raise RuntimeError(f"Missing deterministic IP assignment for scenario Pod asset {instance!r}")

    os_type = str(instance.get("os_type", "ubuntu"))
    profile = pod_config.get_profile(os_type=os_type)
    pod_name = _pod_name(range_id, subnet_name, instance)
    hostname = _sanitize_name(str(instance.get("name", "")).strip() or pod_name, max_length=63)
    labels = _pod_labels(range_id, request_uuid, subnet_name, str(instance.get("uuid", "")))
    pod_manifest = _build_pod_manifest(
        namespace=namespace,
        pod_name=pod_name,
        hostname=hostname,
        network_name=network_name,
        static_ip=static_ip,
        image=profile.image,
        image_pull_policy=pod_config.image_pull_policy,
        labels=labels,
    )
    _apply_pod(core_api, namespace, pod_manifest, api_exception)
    _wait_for_pod_ready(core_api, namespace, pod_name, static_ip, network_name, api_exception)

    return {
        "uuid": str(instance.get("uuid", "")),
        "name": str(instance.get("name", "")).strip() or hostname,
        "asset_type": "scenario_pod",
        "hostname": hostname,
        "role": str(instance.get("role", "victim")),
        "os": os_type,
        "subnet_name": subnet_name,
        "instance_id": pod_name,
        "private_ip": static_ip,
        "ssh_key_secret_arn": "",  # nosec B105 - scenario pods are not SSH-backed assets.
        "ssh_username": "",
        "gdc_pod_name": pod_name,
        "gdc_namespace": namespace,
        "gdc_network_name": str(subnet_output.get("gdc_network_name", "")),
        "gdc_nad_name": str(subnet_output.get("gdc_nad_name", "")),
        "gdc_ip": static_ip,
        "gdc_interface_name": "net1",
        "gdc_container_image": profile.image,
    }


def _delete_scenario_pod_asset(core_api, namespace: str, pod_name: str, api_exception) -> None:
    try:
        core_api.delete_namespaced_pod(name=pod_name, namespace=namespace)
        logger.info("Deleted scenario Pod %s/%s", namespace, pod_name)
    except api_exception as exc:
        if exc.status != 404:
            raise
        return

    try:
        _wait_for_pod_deleted(core_api, namespace, pod_name, api_exception)
    except RuntimeError:
        logger.warning("Timed out waiting for scenario Pod %s/%s to delete", namespace, pod_name)


def _is_pod_ready(
    core_api,
    *,
    namespace: str,
    pod_name: str,
    expected_ip: str,
    network_name: str,
    api_exception,
) -> bool:
    try:
        pod = core_api.read_namespaced_pod(name=pod_name, namespace=namespace).to_dict()
    except api_exception as exc:
        if exc.status == 404:
            return False
        raise

    phase = str(((pod.get("status") or {}).get("phase")) or "").lower()
    assigned_ip = _extract_network_status_ip(pod, network_name, namespace)
    return phase == "running" and assigned_ip == expected_ip


def run_power_operation(operation: str, instance: dict[str, Any]) -> None:
    """Run a start/stop operation for a scenario Pod."""
    if operation not in {"start", "stop"}:
        raise ValueError(f"Unknown scenario Pod operation: {operation}")

    access = load_gdc_network_access_config()
    if access is None:
        raise RuntimeError("GDC range plane requires GDC_ACCESS_SECRET_ID for scenario Pod power operations")

    target = _resolve_power_target(instance)
    pod_config = load_gdc_scenario_pod_config()
    client, _, api_exception = _import_kubernetes_modules()
    api_client = _build_kube_api_client(access.kubeconfig)
    core_api = client.CoreV1Api(api_client)

    namespace = target["namespace"]
    pod_name = target["pod_name"]

    if operation == "stop":
        try:
            core_api.delete_namespaced_pod(name=pod_name, namespace=namespace)
            logger.info("Stopped scenario Pod %s/%s", namespace, pod_name)
        except api_exception as exc:
            if exc.status == 404:
                logger.info("Scenario Pod %s/%s already absent during stop", namespace, pod_name)
                return
            raise
        _wait_for_pod_deleted(core_api, namespace, pod_name, api_exception)
        return

    if _is_pod_ready(
        core_api,
        namespace=namespace,
        pod_name=pod_name,
        expected_ip=target["static_ip"],
        network_name=target["network_name"],
        api_exception=api_exception,
    ):
        logger.info("Scenario Pod %s/%s already running", namespace, pod_name)
        return

    try:
        core_api.delete_namespaced_pod(name=pod_name, namespace=namespace)
        _wait_for_pod_deleted(core_api, namespace, pod_name, api_exception)
    except api_exception as exc:
        if exc.status != 404:
            raise

    pod_manifest = _build_pod_manifest(
        namespace=namespace,
        pod_name=pod_name,
        hostname=target["hostname"],
        network_name=target["network_name"],
        static_ip=target["static_ip"],
        image=target["image"],
        image_pull_policy=pod_config.image_pull_policy,
        labels=target["labels"],
    )
    core_api.create_namespaced_pod(namespace=namespace, body=pod_manifest)
    logger.info("Started scenario Pod %s/%s", namespace, pod_name)
    _wait_for_pod_ready(
        core_api,
        namespace,
        pod_name,
        target["static_ip"],
        target["network_name"],
        api_exception,
    )


def apply_range_assets(
    request_uuid: str,
    variables: dict[str, Any],
    subnet_outputs: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Create or reconcile pod-backed scenario assets on shared GDC L2 networks."""
    access = load_gdc_network_access_config()
    if access is None:
        raise RuntimeError("GDC range plane requires GDC_ACCESS_SECRET_ID to provision scenario Pods")

    pod_config = load_gdc_scenario_pod_config()
    client, _, api_exception = _import_kubernetes_modules()
    api_client = _build_kube_api_client(access.kubeconfig)
    core_api = client.CoreV1Api(api_client)

    range_id = int(variables["range_id"])
    outputs: list[dict[str, Any]] = []
    for subnet in variables.get("subnets", []):
        subnet_name, subnet_output, asset_ip_assignments, namespace, network_name = _build_subnet_pod_context(
            subnet=subnet,
            subnet_outputs=subnet_outputs,
        )

        for index, instance in enumerate(list(subnet.get("instances") or [])):
            if not _is_scenario_pod(instance):
                continue
            outputs.append(
                _create_scenario_pod_asset(
                    core_api=core_api,
                    api_exception=api_exception,
                    pod_config=pod_config,
                    range_id=range_id,
                    request_uuid=request_uuid,
                    subnet_name=subnet_name,
                    subnet_output=subnet_output,
                    asset_ip_assignments=asset_ip_assignments,
                    namespace=namespace,
                    network_name=network_name,
                    instance=instance,
                    index=index,
                )
            )

    return outputs


def destroy_range_assets(
    request_uuid: str,
    variables: dict[str, Any] | None,
    subnet_outputs: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Delete pod-backed scenario assets from the range namespace."""
    del request_uuid
    if not variables:
        return

    access = load_gdc_network_access_config()
    if access is None:
        raise RuntimeError("GDC range plane requires GDC_ACCESS_SECRET_ID to destroy scenario Pods")

    client, _, api_exception = _import_kubernetes_modules()
    api_client = _build_kube_api_client(access.kubeconfig)
    core_api = client.CoreV1Api(api_client)

    range_id = int(variables["range_id"])
    for subnet in variables.get("subnets", []):
        subnet_name = str(subnet.get("name", "")).strip()
        subnet_output = (subnet_outputs or {}).get(subnet_name, {})
        namespace = str(subnet_output.get("gdc_namespace", "")).strip() or _sanitize_name(
            f"{access.namespace_prefix}-{range_id}"
        )

        for instance in subnet.get("instances") or []:
            if not _is_scenario_pod(instance):
                continue
            pod_name = _pod_name(range_id, subnet_name, instance)
            _delete_scenario_pod_asset(core_api, namespace, pod_name, api_exception)
