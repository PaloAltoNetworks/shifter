"""Palo Alto VM-Series lifecycle on GDC VM Runtime."""

from __future__ import annotations

import logging

# subprocess drives kubectl virt start/stop runtime operations (see run_power_operation).
import subprocess  # nosec B404
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from kubernetes.client import CoreV1Api, CustomObjectsApi
    from kubernetes.client.exceptions import ApiException

from config import (
    GDCPaloAltoVMSeriesConfig,
    load_gdc_network_access_config,
    load_gdc_palo_alto_vmseries_config,
)
from gdc_vmruntime_assets import (
    _IMAGE_IMPORT_K8S_NAME,
    _VM_DISK_PLURAL,
    _VM_GROUP,
    _VM_PLURAL,
    _VM_VERSION,
    _apply_namespaced_custom_object,
    _build_disk_manifest,
    _build_kube_api_client,
    _delete_namespaced_custom_object,
    _import_kubernetes_modules,
    _sanitize_name,
    _wait_for_deleted,
    _wait_for_disk_ready,
    _wait_for_vm_ready,
)

# Re-exports from the gdc_vmseries_common / gdc_vmseries_assets split modules
# (Sonar S104). apply_ngfw / destroy_ngfw call these by bare name, so importing
# them into this namespace keeps both the call sites and the
# patch("gdc_vmseries_ngfw.X") test seams working against this module.
from gdc_vmseries_assets import (
    _build_bootstrap_disk_manifest,
    _build_vmseries_vm_manifest,
    _create_bootstrap_iso,
    _delete_bootstrap_iso,
    _delete_ssh_secret,
    _ensure_gcs_image_secret,
    _ensure_namespace,
    _ensure_ssh_secret,
    _extract_interface_ip,
    _ip_from_cidr,
)
from gdc_vmseries_common import (
    _ATTACHMENT_MODE,
    _DATA_INTERFACE_NAME,
    _MGMT_INTERFACE_NAME,
    _PRODUCT,
    _boot_disk_name,
    _bootstrap_disk_name,
    _labels,
    _namespace_name,
    _vm_name,
    _VMSeriesNames,
)

logger = logging.getLogger(__name__)


def _build_provision_result(
    *,
    config: GDCPaloAltoVMSeriesConfig,
    names: _VMSeriesNames,
    bootstrap_gcs_url: str,
    ssh_secret_ref: str,
    management_ip: str,
    dataplane_ip: str,
) -> dict[str, Any]:
    """Assemble the provisioner result/state dict for a created VM-Series instance."""
    data_attachment_id = f"{names.namespace}/{names.vm_name}:{_DATA_INTERFACE_NAME}"
    gcp_metadata = {
        "product": _PRODUCT,
        "namespace": names.namespace,
        "vm_name": names.vm_name,
        "boot_disk_name": names.boot_disk_name,
        "bootstrap_disk_name": names.bootstrap_disk_name,
        "bootstrap_gcs_url": bootstrap_gcs_url,
        "management_network_name": config.management_network_name,
        "management_interface_name": _MGMT_INTERFACE_NAME,
        "management_ip": management_ip,
        "data_network_name": config.data_network_name,
        "data_interface_name": _DATA_INTERFACE_NAME,
        "dataplane_ip": dataplane_ip,
        "route_next_hop_ip": config.route_next_hop_ip,
        "attachment_mode": _ATTACHMENT_MODE,
        "data_attachment_id": data_attachment_id,
        "ssh_key_secret_id": ssh_secret_ref,
        "storage_class_name": config.storage_class_name,
    }
    return {
        "cloud_provider": "gcp",
        "product": _PRODUCT,
        "management_ip": management_ip,
        "dataplane_ip": dataplane_ip,
        "route_next_hop_ip": config.route_next_hop_ip,
        "attachment_mode": _ATTACHMENT_MODE,
        "data_attachment_id": data_attachment_id,
        "data_eni_id": "",
        "ssh_key_secret_arn": ssh_secret_ref,
        "ssh_key_secret_ref": ssh_secret_ref,
        "gdc_namespace": names.namespace,
        "gdc_vm_name": names.vm_name,
        "gdc_boot_disk_name": names.boot_disk_name,
        "gdc_bootstrap_disk_name": names.bootstrap_disk_name,
        "gdc_bootstrap_gcs_url": bootstrap_gcs_url,
        "provider_metadata": {
            "gcp": gcp_metadata,
        },
    }


def _apply_vm_resources(
    custom_api: CustomObjectsApi,
    *,
    config: GDCPaloAltoVMSeriesConfig,
    names: _VMSeriesNames,
    bootstrap_gcs_url: str,
    gcs_secret_name: str | None,
    labels: dict[str, str],
    api_exception: type[ApiException],
) -> dict[str, Any]:
    """Create the boot disk, bootstrap disk, and VirtualMachine; return the ready VM."""
    boot_disk_manifest = _build_disk_manifest(
        namespace=names.namespace,
        disk_name=names.boot_disk_name,
        source_url=config.image_url,
        gcs_secret_name=gcs_secret_name if config.image_url.startswith("gs://") else None,
        disk_size_gib=config.disk_size_gib,
        storage_class_name=config.storage_class_name,
        labels=labels,
    )
    _apply_namespaced_custom_object(
        custom_api,
        group=_VM_GROUP,
        version=_VM_VERSION,
        plural=_VM_DISK_PLURAL,
        namespace=names.namespace,
        body=boot_disk_manifest,
        api_exception=api_exception,
    )
    _wait_for_disk_ready(custom_api, names.namespace, names.boot_disk_name, api_exception)

    bootstrap_disk_manifest = _build_bootstrap_disk_manifest(
        namespace=names.namespace,
        disk_name=names.bootstrap_disk_name,
        source_url=bootstrap_gcs_url,
        gcs_secret_name=gcs_secret_name,
        disk_size_gib=config.bootstrap_disk_size_gib,
        storage_class_name=config.storage_class_name,
        labels=labels,
    )
    _apply_namespaced_custom_object(
        custom_api,
        group=_VM_GROUP,
        version=_VM_VERSION,
        plural=_VM_DISK_PLURAL,
        namespace=names.namespace,
        body=bootstrap_disk_manifest,
        api_exception=api_exception,
    )
    _wait_for_disk_ready(custom_api, names.namespace, names.bootstrap_disk_name, api_exception)

    vm_manifest = _build_vmseries_vm_manifest(
        namespace=names.namespace,
        vm_name=names.vm_name,
        boot_disk_name=names.boot_disk_name,
        bootstrap_disk_name=names.bootstrap_disk_name,
        config=config,
        labels=labels,
    )
    _apply_namespaced_custom_object(
        custom_api,
        group=_VM_GROUP,
        version=_VM_VERSION,
        plural=_VM_PLURAL,
        namespace=names.namespace,
        body=vm_manifest,
        api_exception=api_exception,
    )
    return _wait_for_vm_ready(custom_api, names.namespace, names.vm_name, api_exception)


def apply_ngfw(
    *,
    request_id: str,
    instance_id: str,
    app_spec: dict[str, Any],
) -> dict[str, Any]:
    """Create or reconcile a Palo Alto VM-Series firewall on GDC VM Runtime."""
    access = load_gdc_network_access_config()
    if access is None:
        raise RuntimeError("GDC VM-Series provisioning requires GDC_ACCESS_SECRET_ID")
    config = load_gdc_palo_alto_vmseries_config()

    _, client_module, _, api_exception = _import_kubernetes_modules()
    api_client = _build_kube_api_client(access.kubeconfig)
    core_api = client_module.CoreV1Api(api_client)
    custom_api = client_module.CustomObjectsApi(api_client)

    user_id = int(app_spec.get("user_id", 0))
    namespace = _namespace_name(config, user_id)
    vm_name = _vm_name(user_id, instance_id)
    boot_disk_name = _boot_disk_name(vm_name)
    bootstrap_disk_name = _bootstrap_disk_name(vm_name)
    hostname = _sanitize_name(f"ngfw-user-{user_id}", max_length=31)
    labels = _labels(user_id=user_id, request_id=request_id, instance_id=instance_id)
    names = _VMSeriesNames(
        namespace=namespace,
        vm_name=vm_name,
        boot_disk_name=boot_disk_name,
        bootstrap_disk_name=bootstrap_disk_name,
    )

    _ensure_namespace(core_api, namespace, labels, api_exception)
    gcs_secret_name = _ensure_gcs_image_secret(core_api, client_module, namespace, config, api_exception)
    ssh_secret_ref, public_key = _ensure_ssh_secret(user_id, instance_id)
    bootstrap_gcs_url = _create_bootstrap_iso(
        config=config,
        request_id=request_id,
        instance_id=instance_id,
        hostname=hostname,
        app_spec=app_spec,
        public_key=public_key,
    )

    vm = _apply_vm_resources(
        custom_api,
        config=config,
        names=names,
        bootstrap_gcs_url=bootstrap_gcs_url,
        gcs_secret_name=gcs_secret_name,
        labels=labels,
        api_exception=api_exception,
    )
    management_ip = _ip_from_cidr(config.management_ip_cidr) or _extract_interface_ip(vm, _MGMT_INTERFACE_NAME)
    dataplane_ip = _ip_from_cidr(config.data_ip_cidr) or _extract_interface_ip(vm, _DATA_INTERFACE_NAME)
    if not management_ip:
        raise RuntimeError(f"GDC VM-Series {namespace}/{vm_name} reached running state without a management IP")

    return _build_provision_result(
        config=config,
        names=names,
        bootstrap_gcs_url=bootstrap_gcs_url,
        ssh_secret_ref=ssh_secret_ref,
        management_ip=management_ip,
        dataplane_ip=dataplane_ip,
    )


def _delete_vm_series_resource(
    custom_api: CustomObjectsApi,
    *,
    namespace: str,
    name: str,
    plural: str,
    label: str,
    api_exception: type[ApiException],
) -> None:
    """Delete a namespaced VM-Series custom object and wait for it to disappear.

    A deletion timeout is logged as a warning rather than raised.
    """
    _delete_namespaced_custom_object(
        custom_api,
        group=_VM_GROUP,
        version=_VM_VERSION,
        plural=plural,
        namespace=namespace,
        name=name,
        api_exception=api_exception,
    )
    try:
        _wait_for_deleted(custom_api, namespace, name, _VM_GROUP, _VM_VERSION, plural, api_exception)
    except RuntimeError:
        logger.warning("Timed out waiting for GDC VM-Series %s %s/%s to delete", label, namespace, name)


def _delete_image_import_secret(core_api: CoreV1Api, namespace: str, api_exception: type[ApiException]) -> None:
    """Delete the image-import secret, ignoring an already-absent secret (404)."""
    try:
        core_api.delete_namespaced_secret(name=_IMAGE_IMPORT_K8S_NAME, namespace=namespace)
    except api_exception as exc:
        if exc.status != 404:
            raise


def _state_field(metadata: dict[str, Any], state: dict[str, Any], meta_key: str, state_key: str) -> str:
    """Return a VM-Series state field, preferring provider metadata over top-level state."""
    return str(metadata.get(meta_key) or state.get(state_key, "")).strip()


def destroy_ngfw(state: dict[str, Any]) -> None:
    """Destroy a GDC VM Runtime Palo Alto VM-Series firewall and support assets."""
    access = load_gdc_network_access_config()
    if access is None:
        raise RuntimeError("GDC VM-Series destruction requires GDC_ACCESS_SECRET_ID")

    metadata = dict(state.get("provider_metadata", {}).get("gcp") or {})
    namespace = _state_field(metadata, state, "namespace", "gdc_namespace")
    vm_name = _state_field(metadata, state, "vm_name", "gdc_vm_name")
    boot_disk_name = _state_field(metadata, state, "boot_disk_name", "gdc_boot_disk_name")
    bootstrap_disk_name = _state_field(metadata, state, "bootstrap_disk_name", "gdc_bootstrap_disk_name")
    if not namespace or not vm_name:
        raise RuntimeError("GDC VM-Series state is missing namespace or VM name")

    _, client_module, _, api_exception = _import_kubernetes_modules()
    api_client = _build_kube_api_client(access.kubeconfig)
    core_api = client_module.CoreV1Api(api_client)
    custom_api = client_module.CustomObjectsApi(api_client)

    _delete_vm_series_resource(
        custom_api,
        namespace=namespace,
        name=vm_name,
        plural=_VM_PLURAL,
        label="VM",
        api_exception=api_exception,
    )

    for disk_name in (bootstrap_disk_name, boot_disk_name):
        if not disk_name:
            continue
        _delete_vm_series_resource(
            custom_api,
            namespace=namespace,
            name=disk_name,
            plural=_VM_DISK_PLURAL,
            label="disk",
            api_exception=api_exception,
        )

    _delete_bootstrap_iso(_state_field(metadata, state, "bootstrap_gcs_url", "gdc_bootstrap_gcs_url"))
    _delete_ssh_secret(_state_field(metadata, state, "ssh_key_secret_id", "ssh_key_secret_arn"))
    _delete_image_import_secret(core_api, namespace, api_exception)


def run_power_operation(operation: str, state: dict[str, Any]) -> None:
    """Run a VM-Series start/stop operation through kubectl virt."""
    if operation not in {"start", "stop"}:
        raise ValueError(f"Unknown GDC VM-Series operation: {operation}")

    access = load_gdc_network_access_config()
    if access is None:
        raise RuntimeError("GDC VM-Series runtime operations require GDC_ACCESS_SECRET_ID")

    metadata = dict(state.get("provider_metadata", {}).get("gcp") or {})
    namespace = str(metadata.get("namespace") or state.get("gdc_namespace", "")).strip()
    vm_name = str(metadata.get("vm_name") or state.get("gdc_vm_name", "")).strip()
    if not namespace or not vm_name:
        raise RuntimeError("GDC VM-Series state is missing namespace or VM name")

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as kubeconfig_file:
        kubeconfig_file.write(access.kubeconfig)
        kubeconfig_path = kubeconfig_file.name
    try:
        command = ["kubectl", "--kubeconfig", kubeconfig_path, "virt", operation, vm_name, "--namespace", namespace]
        subprocess.run(command, check=True, capture_output=True)  # noqa: S603
    except FileNotFoundError as exc:
        raise RuntimeError("GDC VM-Series runtime operations require kubectl with the virt plugin") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else str(exc)
        raise RuntimeError(f"kubectl virt {operation} failed for {namespace}/{vm_name}: {stderr}") from exc
    finally:
        Path(kubeconfig_path).unlink(missing_ok=True)
