"""GDC VM Runtime guest lifecycle for the active GCP range plane."""

from __future__ import annotations

import logging
import os
import re
import subprocess  # nosec B404 - used for kubectl virt runtime operations
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from cloud.gcp.base import get_project_id, import_google_module
from components.instance import sanitize_hostname
from config import GDCNetworkAccessConfig, GDCVMRuntimeConfig, load_gdc_network_access_config, load_gdc_vmruntime_config
from executors.factory import get_ssh_username
from utils.crypto import derive_ssh_public_key, generate_ssh_keypair

logger = logging.getLogger(__name__)

_VM_GROUP = "vm.cluster.gke.io"
_VM_VERSION = "v1"
_VM_DISK_PLURAL = "virtualmachinedisks"
_VM_PLURAL = "virtualmachines"
_VMI_GROUP = "kubevirt.io"
_VMI_VERSION = "v1"
_VMI_PLURAL = "virtualmachineinstances"
_TEMPLATES_DIR = Path(__file__).parent / "templates"
_IMAGE_IMPORT_SECRET_SUFFIX = "-".join(("gdc", "vm", "image", "gcs"))
_POLL_INTERVAL_SECONDS = 5
_DISK_READY_TIMEOUT_SECONDS = 1800
_VM_READY_TIMEOUT_SECONDS = 1800
_VM_STOP_TIMEOUT_SECONDS = 900
_DELETE_TIMEOUT_SECONDS = 300
_MANAGED_BY_LABEL = "shifter-provisioner"


def _import_kubernetes_modules():
    try:
        import kubernetes
        from kubernetes import client, config
        from kubernetes.client.exceptions import ApiException
    except ImportError as exc:
        raise RuntimeError("GDC VM Runtime asset lifecycle requires the kubernetes Python client") from exc

    return kubernetes, client, config, ApiException


def _sanitize_name(value: str, *, max_length: int = 63) -> str:
    normalized = re.sub(r"[^a-z0-9-]+", "-", value.strip().lower())
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    normalized = normalized[:max_length].rstrip("-")
    return normalized or "range"


def _build_kube_api_client(kubeconfig_yaml: str):
    _, client, config, _ = _import_kubernetes_modules()
    import yaml

    kubeconfig_dict = yaml.safe_load(kubeconfig_yaml)
    if not isinstance(kubeconfig_dict, dict):
        raise RuntimeError("GDC kubeconfig secret did not decode into a kubeconfig document")

    loader = config.kube_config.KubeConfigLoader(config_dict=kubeconfig_dict)
    configuration = client.Configuration()
    loader.load_and_set(configuration)
    return client.ApiClient(configuration=configuration)


def _instance_token(instance: dict[str, Any]) -> str:
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


def _is_vm_runtime_asset(instance: dict[str, Any]) -> bool:
    """Return True when the instance should be provisioned as a VM Runtime VM."""
    return str(instance.get("asset_type", "vm_runtime_vm")).strip() == "vm_runtime_vm"


def _vm_name(range_id: int, subnet_name: str, instance: dict[str, Any]) -> str:
    token = _instance_token(instance)
    role = _sanitize_name(str(instance.get("role", "vm")), max_length=12)
    return _sanitize_name(f"range-{range_id}-{subnet_name}-{role}-{token}")


def _disk_name(vm_name: str) -> str:
    return _sanitize_name(f"{vm_name}-boot")


def _build_instance_hostname(instance: dict[str, Any], vm_name: str) -> str:
    display_name = str(instance.get("name", "")).strip()
    if display_name:
        return sanitize_hostname(display_name)
    return sanitize_hostname(vm_name, max_length=20)


def _build_instance_secret_name(range_id: int, instance: dict[str, Any]) -> str:
    environment = _sanitize_name(os.environ.get("ENVIRONMENT", "gcp-dev"), max_length=32)
    token = _instance_token(instance)
    role = _sanitize_name(str(instance.get("role", "vm")), max_length=12)
    return _sanitize_name(f"shifter-{environment}-range-{range_id}-{role}-{token}-ssh", max_length=255)


def _load_template(name: str):
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(
            enabled_extensions=("html", "xml"),
            default_for_string=False,
            default=False,
        ),
    )
    return env.get_template(name)


def _get_linux_access_password(os_type: str) -> str:
    if os_type == "kali":
        return os.environ.get("GDC_KALI_PASSWORD", "kali")
    return os.environ.get("GDC_UBUNTU_PASSWORD", "ubuntu")


def _get_windows_admin_password(role: str) -> str:
    if role == "dc":
        return os.environ.get("DC_DOMAIN_PASSWORD") or os.environ.get(
            "GDC_WINDOWS_ADMIN_PASSWORD",
            "CortexSavesTheDay!",
        )
    return os.environ.get("GDC_WINDOWS_ADMIN_PASSWORD", "CortexSavesTheDay!")


def _render_user_data(instance: dict[str, Any], hostname: str, public_key: str) -> str:
    role = str(instance.get("role", "victim"))
    os_type = str(instance.get("os_type", "ubuntu"))

    if role == "dc":
        template = _load_template("dc_windows.ps1.j2")
        admin_password = _get_windows_admin_password(role)
        return template.render(public_key=public_key, admin_password=admin_password)
    if os_type == "windows":
        template = _load_template("victim_windows.ps1.j2")
        return template.render(
            public_key=public_key,
            admin_password=_get_windows_admin_password(role),
        )
    if role == "attacker" or os_type == "kali":
        template = _load_template("kali.sh.j2")
        return template.render(
            hostname=hostname,
            public_key=public_key,
            kali_password=_get_linux_access_password("kali"),
        )

    template = _load_template("victim_linux.sh.j2")
    return template.render(
        public_key=public_key,
        ssh_user=get_ssh_username(os_type, role),
        guest_password=_get_linux_access_password(os_type),
    )


def _resolve_image_source(source_url: str, gcs_secret_name: str | None) -> dict[str, Any]:
    if source_url.startswith("gs://"):
        gcs_source: dict[str, Any] = {"url": source_url}
        if gcs_secret_name:
            gcs_source["secretRef"] = gcs_secret_name
        return {"gcs": gcs_source}
    if source_url.startswith(("http://", "https://")):
        return {"http": {"url": source_url}}
    if source_url.startswith("docker://"):
        return {"registry": {"url": source_url}}
    if source_url.startswith("registry://"):
        return {"registry": {"url": f"docker://{source_url.removeprefix('registry://')}"}}
    if source_url.startswith("oci://"):
        return {"registry": {"url": f"docker://{source_url.removeprefix('oci://')}"}}
    raise RuntimeError(
        f"Unsupported GDC VM Runtime image source {source_url!r}. "
        "Use gs://, http(s)://, docker://, registry://, or oci://."
    )


def _asset_labels(range_id: int, request_uuid: str, subnet_name: str, instance_uuid: str) -> dict[str, str]:
    labels = {
        "app.kubernetes.io/managed-by": _MANAGED_BY_LABEL,
        "shifter.dev/range-id": str(range_id),
        "shifter.dev/request-id": request_uuid,
        "shifter.dev/subnet-name": _sanitize_name(subnet_name),
        "shifter.dev/range-plane": "gdc-vmruntime",
    }
    if instance_uuid:
        labels["shifter.dev/instance-uuid"] = instance_uuid
    return labels


def _build_disk_manifest(
    *,
    namespace: str,
    disk_name: str,
    source_url: str,
    gcs_secret_name: str | None,
    disk_size_gib: int,
    storage_class_name: str,
    labels: dict[str, str],
) -> dict[str, Any]:
    return {
        "apiVersion": f"{_VM_GROUP}/{_VM_VERSION}",
        "kind": "VirtualMachineDisk",
        "metadata": {
            "name": disk_name,
            "namespace": namespace,
            "labels": labels,
        },
        "spec": {
            "size": f"{disk_size_gib}Gi",
            "storageClassName": storage_class_name,
            "source": _resolve_image_source(source_url, gcs_secret_name),
        },
    }


def _build_vm_manifest(
    *,
    namespace: str,
    vm_name: str,
    disk_name: str,
    network_name: str,
    static_ip: str,
    subnet_cidr: str,
    user_data: str,
    os_label: str,
    vcpus: int,
    memory: str,
    labels: dict[str, str],
) -> dict[str, Any]:
    prefix_length = subnet_cidr.split("/", 1)[1]
    return {
        "apiVersion": f"{_VM_GROUP}/{_VM_VERSION}",
        "kind": "VirtualMachine",
        "metadata": {
            "name": vm_name,
            "namespace": namespace,
            "labels": labels,
        },
        "spec": {
            "osType": os_label,
            "compute": {
                "cpu": {"vcpus": vcpus},
                "memory": {"capacity": memory},
            },
            "interfaces": [
                {
                    "name": "eth0",
                    "networkName": network_name,
                    "ipAddresses": [f"{static_ip}/{prefix_length}"],
                    "default": True,
                }
            ],
            "disks": [
                {
                    "boot": True,
                    "autoDelete": False,
                    "virtualMachineDiskName": disk_name,
                }
            ],
            "cloudInit": {
                "noCloud": {
                    "userData": user_data,
                }
            },
        },
    }


def _apply_namespaced_custom_object(
    custom_api,
    *,
    group: str,
    version: str,
    plural: str,
    namespace: str,
    body: dict[str, Any],
    api_exception,
) -> None:
    name = body["metadata"]["name"]
    try:
        custom_api.create_namespaced_custom_object(
            group=group,
            version=version,
            plural=plural,
            namespace=namespace,
            body=body,
        )
        logger.info("Created %s %s/%s", body["kind"], namespace, name)
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
        logger.info("Updated %s %s/%s", body["kind"], namespace, name)


def _delete_namespaced_custom_object(
    custom_api,
    *,
    group: str,
    version: str,
    plural: str,
    namespace: str,
    name: str,
    api_exception,
) -> None:
    try:
        custom_api.delete_namespaced_custom_object(
            group=group,
            version=version,
            plural=plural,
            namespace=namespace,
            name=name,
        )
        logger.info("Deleted %s %s/%s", plural, namespace, name)
    except api_exception as exc:
        if exc.status != 404:
            raise


def _wait_for_disk_ready(custom_api, namespace: str, disk_name: str, api_exception) -> dict[str, Any]:
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
    status = vm.get("status", {})
    for interface in status.get("interfaces", []) or []:
        ip_addresses = interface.get("ipAddresses") or []
        if ip_addresses:
            return str(ip_addresses[0]).split("/", 1)[0]
    return ""


def _wait_for_vm_ready(custom_api, namespace: str, vm_name: str, api_exception) -> dict[str, Any]:
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


def _wait_for_vm_stopped(custom_api, namespace: str, vm_name: str, api_exception) -> dict[str, Any]:
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
    custom_api,
    namespace: str,
    name: str,
    group: str,
    version: str,
    plural: str,
    api_exception,
) -> None:
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


def _read_secret_payload(secret_id: str) -> tuple[str, str]:
    secretmanager = import_google_module("google.cloud.secretmanager")
    google_exceptions = import_google_module("google.api_core.exceptions")
    client = secretmanager.SecretManagerServiceClient()
    if secret_id.startswith("projects/"):
        full_secret_name = secret_id
    else:
        full_secret_name = f"projects/{get_project_id()}/secrets/{secret_id}"
    try:
        response = client.access_secret_version(request={"name": f"{full_secret_name}/versions/latest"})
    except google_exceptions.NotFound:
        raise
    return response.payload.data.decode("utf-8"), full_secret_name


def _ensure_ssh_secret(range_id: int, instance: dict[str, Any]) -> tuple[str, str]:
    project_id = get_project_id()
    if not project_id:
        raise RuntimeError("GCP project ID is required to manage GDC VM Runtime SSH secrets")

    secretmanager = import_google_module("google.cloud.secretmanager")
    google_exceptions = import_google_module("google.api_core.exceptions")
    client = secretmanager.SecretManagerServiceClient()
    secret_id = _build_instance_secret_name(range_id, instance)
    full_secret_name = f"projects/{project_id}/secrets/{secret_id}"

    try:
        response = client.access_secret_version(request={"name": f"{full_secret_name}/versions/latest"})
        private_key = response.payload.data.decode("utf-8")
    except google_exceptions.NotFound:
        private_key, _public_key = generate_ssh_keypair()
        with suppress(google_exceptions.AlreadyExists):
            client.create_secret(
                request={
                    "parent": f"projects/{project_id}",
                    "secret_id": secret_id,
                    "secret": {"replication": {"automatic": {}}},
                }
            )
        client.add_secret_version(
            request={
                "parent": full_secret_name,
                "payload": {"data": private_key.encode("utf-8")},
            }
        )

    return full_secret_name, derive_ssh_public_key(private_key)


def _delete_ssh_secret(range_id: int, instance: dict[str, Any]) -> None:
    project_id = get_project_id()
    if not project_id:
        return

    secretmanager = import_google_module("google.cloud.secretmanager")
    google_exceptions = import_google_module("google.api_core.exceptions")
    client = secretmanager.SecretManagerServiceClient()
    secret_name = f"projects/{project_id}/secrets/{_build_instance_secret_name(range_id, instance)}"
    try:
        client.delete_secret(request={"name": secret_name})
        logger.info("Deleted GDC SSH secret %s", secret_name)
    except google_exceptions.NotFound:
        return


def _ensure_gcs_image_secret(
    core_api,
    client_module,
    namespace: str,
    vm_config: GDCVMRuntimeConfig,
    api_exception,
) -> str | None:
    if not vm_config.image_gcs_secret_id:
        return None

    secret_data, _full_secret_name = _read_secret_payload(vm_config.image_gcs_secret_id)
    body = client_module.V1Secret(
        metadata=client_module.V1ObjectMeta(name=_IMAGE_IMPORT_SECRET_SUFFIX, namespace=namespace),
        type="Opaque",
        string_data={"creds-gcp.json": secret_data},
    )
    try:
        core_api.create_namespaced_secret(namespace=namespace, body=body)
        logger.info("Created GDC VM image access secret %s/%s", namespace, _IMAGE_IMPORT_SECRET_SUFFIX)
    except api_exception as exc:
        if exc.status != 409:
            raise
        core_api.patch_namespaced_secret(name=_IMAGE_IMPORT_SECRET_SUFFIX, namespace=namespace, body=body)
        logger.info("Updated GDC VM image access secret %s/%s", namespace, _IMAGE_IMPORT_SECRET_SUFFIX)
    return _IMAGE_IMPORT_SECRET_SUFFIX


def _collect_vmi_metadata(custom_api, namespace: str, vm_name: str, api_exception) -> dict[str, Any]:
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


def _get_runtime_metadata(state: dict[str, Any]) -> dict[str, Any]:
    provider_metadata = state.get("provider_metadata")
    if not isinstance(provider_metadata, dict):
        return {}

    for provider_name in ("gcp", "gdc"):
        metadata = provider_metadata.get(provider_name)
        if isinstance(metadata, dict):
            return metadata

    return {}


def _resolve_power_target(state: dict[str, Any]) -> tuple[str, str]:
    metadata = _get_runtime_metadata(state)
    namespace = str(metadata.get("namespace") or state.get("gdc_namespace", "")).strip()
    vm_name = str(metadata.get("vm_name") or state.get("gdc_vm_name") or state.get("instance_id", "")).strip()
    if not namespace or not vm_name:
        raise RuntimeError("GDC VM Runtime state is missing namespace or VM name")
    return namespace, vm_name


def _instance_os_label(os_type: str) -> str:
    return "Windows" if os_type == "windows" else "Linux"


def _select_namespace(range_id: int, subnet_outputs: dict[str, dict[str, Any]], access: GDCNetworkAccessConfig) -> str:
    for subnet_output in subnet_outputs.values():
        namespace = str(subnet_output.get("gdc_namespace", "")).strip()
        if namespace:
            return namespace
    return _sanitize_name(f"{access.namespace_prefix}-{range_id}")


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

    range_id = int(variables["range_id"])
    namespace = _select_namespace(range_id, subnet_outputs, access)
    gcs_secret_name = _ensure_gcs_image_secret(core_api, client_module, namespace, vm_config, api_exception)

    pending_instances: list[dict[str, Any]] = []
    for subnet in variables.get("subnets", []):
        subnet_name = str(subnet.get("name", "")).strip()
        subnet_output = subnet_outputs.get(subnet_name, {})
        asset_ip_assignments = dict(subnet_output.get("gdc_asset_ip_assignments") or {})
        subnet_cidr = str(subnet_output.get("subnet_cidr", "")).strip()
        network_name = str(subnet_output.get("gdc_network_name", "")).strip()
        if not subnet_name or not subnet_cidr or not network_name:
            raise RuntimeError(f"GDC subnet output missing network details for {subnet_name!r}")

        instances = list(subnet.get("instances") or [])
        for index, instance in enumerate(instances):
            if not _is_vm_runtime_asset(instance):
                continue
            static_ip = str(asset_ip_assignments.get(_assignment_key(instance, index), "")).strip()
            if not static_ip:
                raise RuntimeError(f"Missing deterministic IP assignment for VM Runtime asset {instance!r}")
            vm_name = _vm_name(range_id, subnet_name, instance)
            disk_name = _disk_name(vm_name)
            hostname = _build_instance_hostname(instance, vm_name)
            ssh_secret_ref, public_key = _ensure_ssh_secret(range_id, instance)
            user_data = _render_user_data(instance, hostname, public_key)
            os_type = str(instance.get("os_type", "ubuntu"))
            profile = vm_config.get_profile(role=str(instance.get("role", "victim")), os_type=os_type)
            labels = _asset_labels(range_id, request_uuid, subnet_name, str(instance.get("uuid", "")))

            disk_manifest = _build_disk_manifest(
                namespace=namespace,
                disk_name=disk_name,
                source_url=profile.source_url,
                gcs_secret_name=gcs_secret_name if profile.source_url.startswith("gs://") else None,
                disk_size_gib=profile.disk_size_gib,
                storage_class_name=vm_config.storage_class_name,
                labels=labels,
            )
            _apply_namespaced_custom_object(
                custom_api,
                group=_VM_GROUP,
                version=_VM_VERSION,
                plural=_VM_DISK_PLURAL,
                namespace=namespace,
                body=disk_manifest,
                api_exception=api_exception,
            )
            _wait_for_disk_ready(custom_api, namespace, disk_name, api_exception)

            vm_manifest = _build_vm_manifest(
                namespace=namespace,
                vm_name=vm_name,
                disk_name=disk_name,
                network_name=network_name,
                static_ip=static_ip,
                subnet_cidr=subnet_cidr,
                user_data=user_data,
                os_label=_instance_os_label(os_type),
                vcpus=profile.vcpus,
                memory=profile.memory,
                labels=labels,
            )
            _apply_namespaced_custom_object(
                custom_api,
                group=_VM_GROUP,
                version=_VM_VERSION,
                plural=_VM_PLURAL,
                namespace=namespace,
                body=vm_manifest,
                api_exception=api_exception,
            )

            pending_instances.append(
                {
                    "instance": instance,
                    "subnet_name": subnet_name,
                    "subnet_output": subnet_output,
                    "vm_name": vm_name,
                    "disk_name": disk_name,
                    "hostname": hostname,
                    "ssh_secret_ref": ssh_secret_ref,
                    "public_key": public_key,
                    "static_ip": static_ip,
                }
            )

    outputs: list[dict[str, Any]] = []
    for pending in pending_instances:
        vm = _wait_for_vm_ready(custom_api, namespace, pending["vm_name"], api_exception)
        private_ip = _extract_vm_ip(vm) or pending["static_ip"]
        vmi_metadata = _collect_vmi_metadata(custom_api, namespace, pending["vm_name"], api_exception)
        instance = pending["instance"]
        subnet_output = pending["subnet_output"]
        os_type = str(instance.get("os_type", "ubuntu"))
        role = str(instance.get("role", "victim"))
        outputs.append(
            {
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
        )

    return outputs


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

    for subnet in subnets:
        subnet_name = str(subnet.get("name", "")).strip()
        for instance in subnet.get("instances") or []:
            if not _is_vm_runtime_asset(instance):
                continue
            vm_name = _vm_name(range_id, subnet_name, instance)
            _delete_namespaced_custom_object(
                custom_api,
                group=_VM_GROUP,
                version=_VM_VERSION,
                plural=_VM_PLURAL,
                namespace=namespace,
                name=vm_name,
                api_exception=api_exception,
            )
            try:
                _wait_for_deleted(custom_api, namespace, vm_name, _VM_GROUP, _VM_VERSION, _VM_PLURAL, api_exception)
            except RuntimeError:
                logger.warning("Timed out waiting for GDC VM %s/%s to delete", namespace, vm_name)

    for subnet in subnets:
        subnet_name = str(subnet.get("name", "")).strip()
        for instance in subnet.get("instances") or []:
            if not _is_vm_runtime_asset(instance):
                continue
            disk_name = _disk_name(_vm_name(range_id, subnet_name, instance))
            _delete_namespaced_custom_object(
                custom_api,
                group=_VM_GROUP,
                version=_VM_VERSION,
                plural=_VM_DISK_PLURAL,
                namespace=namespace,
                name=disk_name,
                api_exception=api_exception,
            )
            try:
                _wait_for_deleted(
                    custom_api,
                    namespace,
                    disk_name,
                    _VM_GROUP,
                    _VM_VERSION,
                    _VM_DISK_PLURAL,
                    api_exception,
                )
            except RuntimeError:
                logger.warning("Timed out waiting for GDC VM disk %s/%s to delete", namespace, disk_name)
            _delete_ssh_secret(range_id, instance)

    if access and access.cluster_id and load_gdc_vmruntime_config().image_gcs_secret_id:
        try:
            core_api.delete_namespaced_secret(name=_IMAGE_IMPORT_SECRET_SUFFIX, namespace=namespace)
        except api_exception as exc:
            if exc.status != 404:
                raise


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
