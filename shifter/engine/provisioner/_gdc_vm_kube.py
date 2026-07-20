"""Kubernetes plumbing for the GDC VM Runtime asset runner.

Generic create/patch/delete/poll helpers against the GDC ``vm.cluster.gke.io``
and ``kubevirt.io`` custom resources, plus the dynamic-import idiom used to
keep the kubernetes client an optional dependency of the provisioner image.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from log_redact import safe_log_fingerprint, safe_log_value

if TYPE_CHECKING:
    from kubernetes.client import ApiClient, CustomObjectsApi
    from kubernetes.client.exceptions import ApiException

logger = logging.getLogger(__name__)

_VM_GROUP = "vm.cluster.gke.io"
_VM_VERSION = "v1"
_VM_DISK_PLURAL = "virtualmachinedisks"
_VM_PLURAL = "virtualmachines"
_VMI_GROUP = "kubevirt.io"
_VMI_VERSION = "v1"
_VMI_PLURAL = "virtualmachineinstances"
_POLL_INTERVAL_SECONDS = 5
_DISK_READY_TIMEOUT_SECONDS = 1800
_VM_READY_TIMEOUT_SECONDS = 1800
_VM_STOP_TIMEOUT_SECONDS = 900
_DELETE_TIMEOUT_SECONDS = 300


def _import_kubernetes_modules() -> tuple[Any, Any, Any, Any]:
    """Import the kubernetes client modules used by the asset runner."""
    try:
        import kubernetes
        from kubernetes import client, config
        from kubernetes.client.exceptions import ApiException
    except ImportError as exc:
        raise RuntimeError("GDC VM Runtime asset lifecycle requires the kubernetes Python client") from exc

    return kubernetes, client, config, ApiException


def _build_kube_api_client(kubeconfig_yaml: str) -> ApiClient:
    """Build a kubernetes ``ApiClient`` from a kubeconfig YAML payload."""
    _, client, config, _ = _import_kubernetes_modules()
    import yaml

    kubeconfig_dict = yaml.safe_load(kubeconfig_yaml)
    if not isinstance(kubeconfig_dict, dict):
        raise RuntimeError("GDC kubeconfig secret did not decode into a kubeconfig document")

    loader = config.kube_config.KubeConfigLoader(config_dict=kubeconfig_dict)
    configuration = client.Configuration()
    loader.load_and_set(configuration)
    return client.ApiClient(configuration=configuration)


def _apply_namespaced_custom_object(
    custom_api: CustomObjectsApi,
    *,
    group: str,
    version: str,
    plural: str,
    namespace: str,
    body: dict[str, Any],
    api_exception: type[ApiException],
) -> None:
    """Create-or-patch a namespaced GDC custom resource."""
    name = body["metadata"]["name"]
    try:
        custom_api.create_namespaced_custom_object(
            group=group,
            version=version,
            plural=plural,
            namespace=namespace,
            body=body,
        )
        logger.info("Created %s %s/%s", safe_log_value(body["kind"]), safe_log_value(namespace), safe_log_value(name))
    except api_exception as exc:
        if exc.status != 409:
            raise
        custom_api.patch_namespaced_custom_object(
            group=group,
            version=version,
            plural=plural,
            namespace=namespace,
            name=name,
            body=body,
        )
        logger.info("Updated %s %s/%s", safe_log_value(body["kind"]), safe_log_value(namespace), safe_log_value(name))


def _delete_namespaced_custom_object(
    custom_api: CustomObjectsApi,
    *,
    group: str,
    version: str,
    plural: str,
    namespace: str,
    name: str,
    api_exception: type[ApiException],
) -> None:
    """Delete a namespaced GDC custom resource, ignoring 404s."""
    try:
        custom_api.delete_namespaced_custom_object(
            group=group,
            version=version,
            plural=plural,
            namespace=namespace,
            name=name,
        )
        logger.info(
            "Deleted %s ns_fp=%s/name_fp=%s",
            safe_log_value(plural),
            safe_log_fingerprint(namespace),
            safe_log_fingerprint(name),
        )
    except api_exception as exc:
        if exc.status != 404:
            raise


def _wait_for_disk_ready(
    custom_api: CustomObjectsApi, namespace: str, disk_name: str, api_exception: type[ApiException]
) -> dict[str, Any]:
    """Poll a VirtualMachineDisk until it reports ``Succeeded`` or fails."""
    deadline = time.monotonic() + _DISK_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            disk = custom_api.get_namespaced_custom_object(
                group=_VM_GROUP,
                version=_VM_VERSION,
                plural=_VM_DISK_PLURAL,
                namespace=namespace,
                name=disk_name,
            )
        except api_exception as exc:
            if exc.status == 404:
                time.sleep(_POLL_INTERVAL_SECONDS)
                continue
            raise

        status = disk.get("status", {})
        phase = str(status.get("phase", "")).lower()
        if phase == "succeeded":
            return disk
        if phase == "failed":
            raise RuntimeError(f"VirtualMachineDisk {namespace}/{disk_name} failed to import")
        time.sleep(_POLL_INTERVAL_SECONDS)

    raise RuntimeError(f"Timed out waiting for VirtualMachineDisk {namespace}/{disk_name} to become ready")


def _extract_vm_ip(vm: dict[str, Any]) -> str:
    """Return the first reported VM IPv4 address, or an empty string."""
    status = vm.get("status", {})
    for interface in status.get("interfaces", []) or []:
        ip_addresses = interface.get("ipAddresses") or []
        if ip_addresses:
            return str(ip_addresses[0]).split("/", 1)[0]
    return ""


def _wait_for_vm_ready(
    custom_api: CustomObjectsApi, namespace: str, vm_name: str, api_exception: type[ApiException]
) -> dict[str, Any]:
    """Poll a VirtualMachine until it is running with a network IP."""
    deadline = time.monotonic() + _VM_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            vm = custom_api.get_namespaced_custom_object(
                group=_VM_GROUP,
                version=_VM_VERSION,
                plural=_VM_PLURAL,
                namespace=namespace,
                name=vm_name,
            )
        except api_exception as exc:
            if exc.status == 404:
                time.sleep(_POLL_INTERVAL_SECONDS)
                continue
            raise

        status = vm.get("status", {})
        state = str(status.get("state", "")).lower()
        private_ip = _extract_vm_ip(vm)
        if state == "running" and private_ip:
            return vm
        if state in {"failed", "error"}:
            raise RuntimeError(f"VirtualMachine {namespace}/{vm_name} entered state={state}")
        time.sleep(_POLL_INTERVAL_SECONDS)

    raise RuntimeError(f"Timed out waiting for VirtualMachine {namespace}/{vm_name} to become ready")


def _wait_for_vm_stopped(
    custom_api: CustomObjectsApi, namespace: str, vm_name: str, api_exception: type[ApiException]
) -> dict[str, Any]:
    """Poll a VirtualMachine until it reaches the stopped state."""
    deadline = time.monotonic() + _VM_STOP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            vm = custom_api.get_namespaced_custom_object(
                group=_VM_GROUP,
                version=_VM_VERSION,
                plural=_VM_PLURAL,
                namespace=namespace,
                name=vm_name,
            )
        except api_exception as exc:
            if exc.status == 404:
                time.sleep(_POLL_INTERVAL_SECONDS)
                continue
            raise

        status = vm.get("status", {})
        state = str(status.get("state", "")).lower()
        if state == "stopped":
            return vm
        if state in {"failed", "error"}:
            raise RuntimeError(f"VirtualMachine {namespace}/{vm_name} entered state={state}")
        time.sleep(_POLL_INTERVAL_SECONDS)

    raise RuntimeError(f"Timed out waiting for VirtualMachine {namespace}/{vm_name} to stop")


def _wait_for_deleted(
    custom_api: CustomObjectsApi,
    namespace: str,
    name: str,
    group: str,
    version: str,
    plural: str,
    api_exception: type[ApiException],
) -> None:
    """Poll until a custom resource is gone (404) or the deadline elapses."""
    deadline = time.monotonic() + _DELETE_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            custom_api.get_namespaced_custom_object(
                group=group,
                version=version,
                plural=plural,
                namespace=namespace,
                name=name,
            )
        except api_exception as exc:
            if exc.status == 404:
                return
            raise
        time.sleep(_POLL_INTERVAL_SECONDS)

    raise RuntimeError(f"Timed out waiting for {plural} {namespace}/{name} to delete")


def _collect_vmi_metadata(
    custom_api: CustomObjectsApi, namespace: str, vm_name: str, api_exception: type[ApiException]
) -> dict[str, Any]:
    """Return VirtualMachineInstance metadata (VMI name, node name) for a VM."""
    try:
        vmi = custom_api.get_namespaced_custom_object(
            group=_VMI_GROUP,
            version=_VMI_VERSION,
            plural=_VMI_PLURAL,
            namespace=namespace,
            name=vm_name,
        )
    except api_exception as exc:
        if exc.status == 404:
            return {}
        raise

    status = vmi.get("status", {})
    metadata = {
        "gdc_vmi_name": str(vmi.get("metadata", {}).get("name", "")).strip(),
        "gdc_node_name": str(status.get("nodeName", "")).strip(),
    }
    return {key: value for key, value in metadata.items() if value}
