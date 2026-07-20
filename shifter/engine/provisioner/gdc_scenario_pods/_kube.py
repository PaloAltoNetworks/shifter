"""Kubernetes client construction and Pod apply/wait helpers for GDC scenario Pods."""

from __future__ import annotations

import json
import logging
import time
from types import ModuleType
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from kubernetes.client import ApiClient, CoreV1Api
    from kubernetes.client.exceptions import ApiException

logger = logging.getLogger(__name__)

_NETWORK_STATUS_ANNOTATION = "k8s.v1.cni.cncf.io/network-status"
_POLL_INTERVAL_SECONDS = 5
_READY_TIMEOUT_SECONDS = 600
_DELETE_TIMEOUT_SECONDS = 300


def _import_kubernetes_modules() -> tuple[ModuleType, ModuleType, type[ApiException]]:
    """Lazily import the kubernetes client/config modules and ApiException type."""
    try:
        from kubernetes import client, config
        from kubernetes.client.exceptions import ApiException
    except ImportError as exc:
        raise RuntimeError("GDC scenario Pod lifecycle requires the kubernetes Python client") from exc

    return client, config, ApiException


def _build_kube_api_client(kubeconfig_yaml: str) -> ApiClient:
    """Build an authenticated Kubernetes ApiClient from a GDC kubeconfig YAML string."""
    # Late-bound call to ``gdc_scenario_pods._import_kubernetes_modules`` so
    # test patches applied at the package level still apply here.
    import gdc_scenario_pods as _pkg

    client, config, _ = _pkg._import_kubernetes_modules()
    kubeconfig_dict = yaml.safe_load(kubeconfig_yaml)
    if not isinstance(kubeconfig_dict, dict):
        raise RuntimeError("GDC kubeconfig secret did not decode into a kubeconfig document")

    loader = config.kube_config.KubeConfigLoader(config_dict=kubeconfig_dict)
    configuration = client.Configuration()
    loader.load_and_set(configuration)
    return client.ApiClient(configuration=configuration)


def _apply_pod(core_api: CoreV1Api, namespace: str, body: dict[str, Any], api_exception: type[ApiException]) -> None:
    """Create the scenario Pod, falling back to an update patch on a 409 conflict."""
    name = body["metadata"]["name"]
    try:
        core_api.create_namespaced_pod(namespace=namespace, body=body)
        logger.info("Created scenario Pod %s/%s", namespace, name)
    except api_exception as exc:
        if exc.status != 409:
            raise
        core_api.patch_namespaced_pod(name=name, namespace=namespace, body=body)
        logger.info("Updated scenario Pod %s/%s", namespace, name)


def _parse_network_status(raw_status: str | None) -> list[Any] | None:
    """Parse the raw network-status annotation JSON; return None if absent or not a list."""
    if not raw_status:
        return None
    try:
        parsed = json.loads(raw_status)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, list) else None


def _ip_from_network_status(network_status: list[Any], expected_names: set[str]) -> str:
    """Return the first matching attachment's IP (without CIDR suffix), or "" if none match."""
    for attachment in network_status:
        if not isinstance(attachment, dict):
            continue
        if attachment.get("name") not in expected_names and attachment.get("interface") != "net1":
            continue
        ips = attachment.get("ips") or []
        if ips:
            return str(ips[0]).split("/", 1)[0]
    return ""


def _extract_network_status_ip(pod: dict[str, Any], network_name: str, namespace: str) -> str:
    """Return the Pod's assigned IP from its network-status annotation, or "" if unavailable."""
    annotations = pod.get("metadata", {}).get("annotations") or {}
    network_status = _parse_network_status(annotations.get(_NETWORK_STATUS_ANNOTATION))
    if network_status is None:
        return ""
    expected_names = {network_name, f"{namespace}/{network_name}"}
    return _ip_from_network_status(network_status, expected_names)


def _wait_for_pod_ready(
    core_api: CoreV1Api,
    namespace: str,
    pod_name: str,
    expected_ip: str,
    network_name: str,
    api_exception: type[ApiException],
) -> None:
    """Poll until the Pod is Running with its expected network IP, or raise on timeout/failure."""
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


def _wait_for_pod_deleted(
    core_api: CoreV1Api, namespace: str, pod_name: str, api_exception: type[ApiException]
) -> None:
    """Poll until the Pod is deleted (404), or raise on timeout."""
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


def _is_pod_ready(
    core_api: CoreV1Api,
    *,
    namespace: str,
    pod_name: str,
    expected_ip: str,
    network_name: str,
    api_exception: type[ApiException],
) -> bool:
    """Return True when the Pod is Running with its expected network-status IP."""
    try:
        pod = core_api.read_namespaced_pod(name=pod_name, namespace=namespace).to_dict()
    except api_exception as exc:
        if exc.status == 404:
            return False
        raise

    phase = str(((pod.get("status") or {}).get("phase")) or "").lower()
    assigned_ip = _extract_network_status_ip(pod, network_name, namespace)
    return phase == "running" and assigned_ip == expected_ip
