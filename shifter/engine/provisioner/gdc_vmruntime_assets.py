"""GDC VM Runtime guest lifecycle for the active GCP range plane.

Public entry points: :func:`apply_range_assets`,
:func:`destroy_range_assets`, :func:`run_power_operation`. Internal
helpers live in private sibling modules (``_gdc_vm_naming``,
``_gdc_vm_templates``, ``_gdc_vm_image_source``, ``_gdc_vm_secrets``,
``_gdc_vm_kube``, ``_gdc_vm_disks``, ``_gdc_vm_runner``) and are re-imported
here so ``gdc_vmseries_ngfw`` callers and existing
``patch("gdc_vmruntime_assets.X")`` test fixtures keep working unchanged.
"""

from __future__ import annotations

import logging

# Bandit B404 suppressed; the subprocess module is used for kubectl virt runtime operations.
import subprocess  # nosec B404  # NOSONAR — bandit suppression must stay inline (S139)
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from _gdc_vm_disks import (
    _asset_labels,
    _build_disk_manifest,
    _build_vm_manifest,
    _VMComputeSpec,
    _VMNetworkSpec,
)
from _gdc_vm_image_source import _resolve_image_source
from _gdc_vm_kube import (
    _VM_DISK_PLURAL,
    _VM_GROUP,
    _VM_PLURAL,
    _VM_VERSION,
    _apply_namespaced_custom_object,
    _build_kube_api_client,
    _collect_vmi_metadata,
    _delete_namespaced_custom_object,
    _extract_vm_ip,
    _import_kubernetes_modules,
    _wait_for_deleted,
    _wait_for_disk_ready,
    _wait_for_vm_ready,
    _wait_for_vm_stopped,
)
from _gdc_vm_naming import (
    _assignment_key,
    _build_instance_hostname,
    _disk_name,
    _sanitize_name,
    _vm_name,
)
from _gdc_vm_runner import (
    _build_subnet_pending_instances,
    _instance_os_label,
    _iter_vm_runtime_instances,
    _KubeAccess,
    _resolve_power_target,
    _select_namespace,
    _SubnetContext,
    _VMRuntimeRunContext,
)
from _gdc_vm_secrets import (
    _IMAGE_IMPORT_K8S_NAME,
    _delete_rdp_password_secret,
    _delete_ssh_secret,
    _ensure_gcs_image_secret,
    _ensure_rdp_password_secret,
    _ensure_ssh_secret,
    _read_secret_payload,
)
from _gdc_vm_templates import _render_user_data
from config import load_gdc_network_access_config, load_gdc_vmruntime_config
from executors.factory import get_ssh_username
from log_redact import safe_log_value

if TYPE_CHECKING:
    from kubernetes.client import CoreV1Api, CustomObjectsApi
    from kubernetes.client.exceptions import ApiException

logger = logging.getLogger(__name__)

# Re-exports for ``gdc_vmseries_ngfw`` and test patches; keep them in
# ``__all__`` so Pyflakes (F401) does not flag them as unused imports.
__all__ = [
    "_IMAGE_IMPORT_K8S_NAME",
    "_VM_DISK_PLURAL",
    "_VM_GROUP",
    "_VM_PLURAL",
    "_VM_VERSION",
    "_apply_namespaced_custom_object",
    "_build_disk_manifest",
    "_build_kube_api_client",
    "_delete_namespaced_custom_object",
    "_import_kubernetes_modules",
    "_read_secret_payload",
    "_resolve_image_source",
    "_sanitize_name",
    "_wait_for_deleted",
    "_wait_for_disk_ready",
    "_wait_for_vm_ready",
    "apply_range_assets",
    "destroy_range_assets",
    "run_power_operation",
]


def _delete_vm_runtime_resource(
    custom_api: CustomObjectsApi,
    *,
    namespace: str,
    name: str,
    plural: str,
    label: str,
    api_exception: type[ApiException],
) -> None:
    """Delete a GDC VM-Runtime resource and wait for its removal, logging timeouts."""
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
        logger.warning(
            "Timed out waiting for GDC %s %s/%s to delete",
            safe_log_value(label),
            safe_log_value(namespace),
            safe_log_value(name),
        )


def _build_pending_vm_runtime_instance(
    *,
    run: _VMRuntimeRunContext,
    instance: dict[str, Any],
    index: int,
    subnet: _SubnetContext,
) -> dict[str, Any]:
    """Apply disk + VM manifests for a single instance and return its pending record."""
    range_id = run.range_id
    request_uuid = run.request_uuid
    vm_config = run.vm_config
    gcs_secret_name = run.gcs_secret_name
    kube = run.kube
    static_ip = str(subnet.asset_ip_assignments.get(_assignment_key(instance, index), "")).strip()
    if not static_ip:
        raise RuntimeError(f"Missing deterministic IP assignment for VM Runtime asset {instance!r}")
    vm_name = _vm_name(range_id, subnet.subnet_name, instance)
    disk_name = _disk_name(vm_name)
    hostname = _build_instance_hostname(instance, vm_name)
    ssh_secret_ref, public_key = _ensure_ssh_secret(range_id, instance)
    role = str(instance.get("role", "victim"))
    # DC keeps DC_DOMAIN_PASSWORD (deployment-scoped); per-instance
    # password is only created for non-DC guests (#762). The value is
    # stored in GCP Secret Manager here at provisioning time; the
    # engine provisioner sets it on the guest post-boot via SSH using
    # the per-instance SSH key.
    if role == "dc":
        rdp_password_secret_ref: str | None = None
    else:
        rdp_password_secret_ref, _ = _ensure_rdp_password_secret(range_id, instance)
    user_data = _render_user_data(instance, hostname, public_key)
    os_type = str(instance.get("os_type", "ubuntu"))
    profile = vm_config.get_profile(role=str(instance.get("role", "victim")), os_type=os_type)
    labels = _asset_labels(range_id, request_uuid, subnet.subnet_name, str(instance.get("uuid", "")))
    disk_manifest = _build_disk_manifest(
        namespace=subnet.namespace,
        disk_name=disk_name,
        source_url=profile.source_url,
        gcs_secret_name=gcs_secret_name if profile.source_url.startswith("gs://") else None,
        disk_size_gib=profile.disk_size_gib,
        storage_class_name=vm_config.storage_class_name,
        labels=labels,
    )
    _apply_namespaced_custom_object(
        kube.custom_api,
        group=_VM_GROUP,
        version=_VM_VERSION,
        plural=_VM_DISK_PLURAL,
        namespace=subnet.namespace,
        body=disk_manifest,
        api_exception=kube.api_exception,
    )
    _wait_for_disk_ready(kube.custom_api, subnet.namespace, disk_name, kube.api_exception)

    vm_manifest = _build_vm_manifest(
        namespace=subnet.namespace,
        vm_name=vm_name,
        disk_name=disk_name,
        user_data=user_data,
        labels=labels,
        network=_VMNetworkSpec(
            network_name=subnet.network_name,
            static_ip=static_ip,
            subnet_cidr=subnet.subnet_cidr,
        ),
        compute=_VMComputeSpec(
            os_label=_instance_os_label(os_type),
            vcpus=profile.vcpus,
            memory=profile.memory,
        ),
    )
    _apply_namespaced_custom_object(
        kube.custom_api,
        group=_VM_GROUP,
        version=_VM_VERSION,
        plural=_VM_PLURAL,
        namespace=subnet.namespace,
        body=vm_manifest,
        api_exception=kube.api_exception,
    )
    return {
        "instance": instance,
        "subnet_name": subnet.subnet_name,
        "vm_name": vm_name,
        "disk_name": disk_name,
        "hostname": hostname,
        "ssh_secret_ref": ssh_secret_ref,
        "rdp_password_secret_ref": rdp_password_secret_ref,
        "public_key": public_key,
        "static_ip": static_ip,
    }


def _build_vm_runtime_output(
    *,
    namespace: str,
    pending: dict[str, Any],
    custom_api: CustomObjectsApi,
    api_exception: type[ApiException],
) -> dict[str, Any]:
    """Wait for a pending VM to become ready and return its provisioner output dict."""
    vm = _wait_for_vm_ready(custom_api, namespace, pending["vm_name"], api_exception)
    private_ip = _extract_vm_ip(vm) or pending["static_ip"]
    vmi_metadata = _collect_vmi_metadata(custom_api, namespace, pending["vm_name"], api_exception)
    instance = pending["instance"]
    subnet_output = pending["subnet_output"]
    os_type = str(instance.get("os_type", "ubuntu"))
    role = str(instance.get("role", "victim"))
    rdp_password_secret_ref = pending.get("rdp_password_secret_ref")
    output: dict[str, Any] = {
        "uuid": str(instance.get("uuid", "")),
        "name": str(instance.get("name", "")).strip() or pending["hostname"],
        "asset_type": "vm_runtime_vm",
        "hostname": pending["hostname"],
        "role": role,
        "os": os_type,
        "subnet_name": pending["subnet_name"],
        "instance_id": pending["vm_name"],
        "private_ip": private_ip,
        "public_key": pending["public_key"],
        "ssh_key_secret_arn": pending["ssh_secret_ref"],
        "ssh_username": get_ssh_username(os_type, role),
        "gdc_vm_name": pending["vm_name"],
        "gdc_namespace": namespace,
        "gdc_network_name": str(subnet_output.get("gdc_network_name", "")),
        "gdc_nad_name": str(subnet_output.get("gdc_nad_name", "")),
        "gdc_ip": private_ip,
        "gdc_interface_name": "eth0",
        "vmruntime_disk_name": pending["disk_name"],
        **vmi_metadata,
    }
    if rdp_password_secret_ref:
        # Surface the reference both at the top-level (mirrors the
        # AWS Terraform output's ssh_key_secret_arn / rdp_password_secret_arn
        # pattern) and inside the gdc_-prefixed alias so the provisioner
        # state writer's _extract_provider_metadata picks it up in the
        # gcp provider_metadata block.
        output["rdp_password_secret_arn"] = rdp_password_secret_ref
        output["gdc_rdp_password_secret_ref"] = rdp_password_secret_ref
    return output


def _destroy_vm_runtime_vms(
    *,
    custom_api: CustomObjectsApi,
    namespace: str,
    range_id: int,
    assets: list[tuple[str, dict[str, Any]]],
    api_exception: type[ApiException],
) -> None:
    """Delete every VirtualMachine resource owned by a range."""
    for subnet_name, instance in assets:
        vm_name = _vm_name(range_id, subnet_name, instance)
        _delete_vm_runtime_resource(
            custom_api,
            namespace=namespace,
            name=vm_name,
            plural=_VM_PLURAL,
            label="VM",
            api_exception=api_exception,
        )


def _destroy_vm_runtime_disks_and_secrets(
    *,
    custom_api: CustomObjectsApi,
    namespace: str,
    range_id: int,
    assets: list[tuple[str, dict[str, Any]]],
    api_exception: type[ApiException],
) -> None:
    """Delete every VirtualMachineDisk and per-instance secret owned by a range."""
    for subnet_name, instance in assets:
        disk_name = _disk_name(_vm_name(range_id, subnet_name, instance))
        _delete_vm_runtime_resource(
            custom_api,
            namespace=namespace,
            name=disk_name,
            plural=_VM_DISK_PLURAL,
            label="VM disk",
            api_exception=api_exception,
        )
        _delete_ssh_secret(range_id, instance)
        _delete_rdp_password_secret(range_id, instance)


def _delete_image_import_secret_if_needed(
    *,
    core_api: CoreV1Api,
    namespace: str,
    api_exception: type[ApiException],
) -> None:
    """Delete the GCS image-pull Secret if one was configured for the range plane."""
    image_gcs_secret_id = load_gdc_vmruntime_config().image_gcs_secret_id
    if not image_gcs_secret_id:
        return
    try:
        core_api.delete_namespaced_secret(name=_IMAGE_IMPORT_K8S_NAME, namespace=namespace)
    except api_exception as exc:
        if exc.status != 404:
            raise


def apply_range_assets(
    request_uuid: str,
    variables: dict[str, Any],
    subnet_outputs: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Create or reconcile VM Runtime guest assets inside the range namespace."""
    access = load_gdc_network_access_config()
    if access is None:
        raise RuntimeError("GDC range plane requires GDC_ACCESS_SECRET_ID to provision VM Runtime assets")

    vm_config = load_gdc_vmruntime_config()
    if not any(subnet.get("instances") for subnet in variables.get("subnets", [])):
        return []

    _, client_module, _, api_exception = _import_kubernetes_modules()
    api_client = _build_kube_api_client(access.kubeconfig)
    custom_api = client_module.CustomObjectsApi(api_client)
    core_api = client_module.CoreV1Api(api_client)
    kube = _KubeAccess(custom_api=custom_api, api_exception=api_exception)

    range_id = int(variables["range_id"])
    namespace = _select_namespace(range_id, subnet_outputs, access)
    gcs_secret_name = _ensure_gcs_image_secret(core_api, client_module, namespace, vm_config, api_exception)
    run = _VMRuntimeRunContext(
        range_id=range_id,
        request_uuid=request_uuid,
        vm_config=vm_config,
        gcs_secret_name=gcs_secret_name,
        kube=kube,
    )

    pending_instances: list[dict[str, Any]] = []
    for subnet in variables.get("subnets", []):
        pending_instances.extend(
            _build_subnet_pending_instances(
                subnet=subnet,
                subnet_outputs=subnet_outputs,
                namespace=namespace,
                run=run,
                build_instance=_build_pending_vm_runtime_instance,
            )
        )

    return [
        _build_vm_runtime_output(
            namespace=namespace,
            pending=pending,
            custom_api=custom_api,
            api_exception=api_exception,
        )
        for pending in pending_instances
    ]


def destroy_range_assets(
    request_uuid: str,
    variables: dict[str, Any] | None,
    subnet_outputs: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Delete VM Runtime guest assets and their SSH secrets for a range."""
    del request_uuid
    if not variables:
        return

    access = load_gdc_network_access_config()
    if access is None:
        raise RuntimeError("GDC range plane requires GDC_ACCESS_SECRET_ID to destroy VM Runtime assets")

    subnets = variables.get("subnets", [])
    if not any(subnet.get("instances") for subnet in subnets):
        return

    _, client_module, _, api_exception = _import_kubernetes_modules()
    api_client = _build_kube_api_client(access.kubeconfig)
    custom_api = client_module.CustomObjectsApi(api_client)
    core_api = client_module.CoreV1Api(api_client)

    range_id = int(variables["range_id"])
    namespace = _select_namespace(range_id, subnet_outputs or {}, access)
    assets = _iter_vm_runtime_instances(subnets)
    _destroy_vm_runtime_vms(
        custom_api=custom_api,
        namespace=namespace,
        range_id=range_id,
        assets=assets,
        api_exception=api_exception,
    )
    _destroy_vm_runtime_disks_and_secrets(
        custom_api=custom_api,
        namespace=namespace,
        range_id=range_id,
        assets=assets,
        api_exception=api_exception,
    )
    _delete_image_import_secret_if_needed(
        core_api=core_api,
        namespace=namespace,
        api_exception=api_exception,
    )


def run_power_operation(operation: str, state: dict[str, Any]) -> None:
    """Run a VM Runtime start/stop operation through kubectl virt and wait for completion."""
    if operation not in {"start", "stop"}:
        raise ValueError(f"Unknown GDC VM Runtime operation: {operation}")

    access = load_gdc_network_access_config()
    if access is None:
        raise RuntimeError("GDC VM Runtime power operations require GDC_ACCESS_SECRET_ID")

    namespace, vm_name = _resolve_power_target(state)

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as kubeconfig_file:
        kubeconfig_file.write(access.kubeconfig)
        kubeconfig_path = kubeconfig_file.name

    try:
        command = ["kubectl", "--kubeconfig", kubeconfig_path, "virt", operation, vm_name, "--namespace", namespace]

        # tokens (see _sanitize_name) and the binary path is resolved via PATH; not a
        # user-controlled command line.
        subprocess.run(command, check=True, capture_output=True)  # noqa: S603
    except FileNotFoundError as exc:
        raise RuntimeError("GDC VM Runtime power operations require kubectl with the virt plugin") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else str(exc)
        raise RuntimeError(f"kubectl virt {operation} failed for {namespace}/{vm_name}: {stderr}") from exc
    finally:
        Path(kubeconfig_path).unlink(missing_ok=True)

    _, client_module, _, api_exception = _import_kubernetes_modules()
    api_client = _build_kube_api_client(access.kubeconfig)
    custom_api = client_module.CustomObjectsApi(api_client)
    if operation == "start":
        _wait_for_vm_ready(custom_api, namespace, vm_name, api_exception)
    else:
        _wait_for_vm_stopped(custom_api, namespace, vm_name, api_exception)
