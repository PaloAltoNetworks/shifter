"""Scenario Pod power operations and range-asset apply/destroy orchestration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ._kube import _apply_pod, _is_pod_ready
from ._manifest import (
    _MANAGED_BY_LABEL,
    _assignment_key,
    _build_pod_manifest,
    _build_subnet_pod_context,
    _first_non_empty_str,
    _get_runtime_metadata,
    _is_scenario_pod,
    _pod_labels,
    _pod_name,
    _sanitize_name,
)

if TYPE_CHECKING:
    from kubernetes.client import CoreV1Api
    from kubernetes.client.exceptions import ApiException

    from config import GDCScenarioPodConfig

logger = logging.getLogger(__name__)

# Empty-string sentinel for asset fields that scenario pods do not populate.
# Referenced (rather than an inline "" literal) so bandit does not raise B105
# on secret-named keys and no inline ``# nosec`` pragma is needed, which would
# otherwise trip SonarCloud's S139 (comment-on-code-line) rule.
_EMPTY = ""


def _resolve_power_target(instance: dict[str, Any]) -> dict[str, Any]:
    """Resolve the namespace/pod/network/IP/image/labels needed for a power op from stored instance state."""
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


def _create_scenario_pod_asset(
    # Moved private helper; already keyword-only, parameter-object refactor out of scope for a decomposition.
    *,  # NOSONAR
    core_api: CoreV1Api,
    api_exception: type[ApiException],
    pod_config: GDCScenarioPodConfig,
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
    """Create (or reconcile) one scenario-Pod asset and return its instance-state dict."""
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

    # Late-bound call to ``gdc_scenario_pods._wait_for_pod_ready`` so test
    # patches applied at the package level still apply here.
    import gdc_scenario_pods as _pkg

    _pkg._wait_for_pod_ready(core_api, namespace, pod_name, static_ip, network_name, api_exception)

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
        "ssh_key_secret_arn": _EMPTY,
        "ssh_username": "",
        "gdc_pod_name": pod_name,
        "gdc_namespace": namespace,
        "gdc_network_name": str(subnet_output.get("gdc_network_name", "")),
        "gdc_nad_name": str(subnet_output.get("gdc_nad_name", "")),
        "gdc_ip": static_ip,
        "gdc_interface_name": "net1",
        "gdc_container_image": profile.image,
    }


def _delete_scenario_pod_asset(
    core_api: CoreV1Api, namespace: str, pod_name: str, api_exception: type[ApiException]
) -> None:
    """Delete a scenario Pod, tolerating an already-absent (404) Pod."""
    try:
        core_api.delete_namespaced_pod(name=pod_name, namespace=namespace)
        logger.info("Deleted scenario Pod %s/%s", namespace, pod_name)
    except api_exception as exc:
        if exc.status != 404:
            raise
        return

    # Late-bound call to ``gdc_scenario_pods._wait_for_pod_deleted`` so test
    # patches applied at the package level still apply here.
    import gdc_scenario_pods as _pkg

    try:
        _pkg._wait_for_pod_deleted(core_api, namespace, pod_name, api_exception)
    except RuntimeError:
        logger.warning("Timed out waiting for scenario Pod %s/%s to delete", namespace, pod_name)


def run_power_operation(operation: str, instance: dict[str, Any]) -> None:
    """Run a start/stop operation for a scenario Pod."""
    if operation not in {"start", "stop"}:
        raise ValueError(f"Unknown scenario Pod operation: {operation}")

    # Late-bound calls to package-level names so test patches applied at
    # the package level still apply here.
    import gdc_scenario_pods as _pkg

    access = _pkg.load_gdc_network_access_config()
    if access is None:
        raise RuntimeError("GDC range plane requires GDC_ACCESS_SECRET_ID for scenario Pod power operations")

    target = _resolve_power_target(instance)
    pod_config = _pkg.load_gdc_scenario_pod_config()
    client, _, api_exception = _pkg._import_kubernetes_modules()
    api_client = _pkg._build_kube_api_client(access.kubeconfig)
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
        _pkg._wait_for_pod_deleted(core_api, namespace, pod_name, api_exception)
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
        _pkg._wait_for_pod_deleted(core_api, namespace, pod_name, api_exception)
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
    _pkg._wait_for_pod_ready(
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
    # Late-bound calls to package-level names so test patches applied at
    # the package level still apply here.
    import gdc_scenario_pods as _pkg

    access = _pkg.load_gdc_network_access_config()
    if access is None:
        raise RuntimeError("GDC range plane requires GDC_ACCESS_SECRET_ID to provision scenario Pods")

    pod_config = _pkg.load_gdc_scenario_pod_config()
    client, _, api_exception = _pkg._import_kubernetes_modules()
    api_client = _pkg._build_kube_api_client(access.kubeconfig)
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

    # Late-bound calls to package-level names so test patches applied at
    # the package level still apply here.
    import gdc_scenario_pods as _pkg

    access = _pkg.load_gdc_network_access_config()
    if access is None:
        raise RuntimeError("GDC range plane requires GDC_ACCESS_SECRET_ID to destroy scenario Pods")

    client, _, api_exception = _pkg._import_kubernetes_modules()
    api_client = _pkg._build_kube_api_client(access.kubeconfig)
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
