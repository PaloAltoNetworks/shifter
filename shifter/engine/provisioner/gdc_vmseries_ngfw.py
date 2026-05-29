"""Palo Alto VM-Series lifecycle on GDC VM Runtime."""

from __future__ import annotations

import logging
import os
import subprocess  # nosec B404 - used for kubectl virt runtime operations
import tempfile
from pathlib import Path
from typing import Any

from jinja2 import Environment, select_autoescape

from cloud.gcp.base import get_project_id, import_google_module
from config import (
    GDCPaloAltoVMSeriesConfig,
    load_gdc_network_access_config,
    load_gdc_palo_alto_vmseries_config,
)
from gdc_vmruntime_assets import (
    _IMAGE_IMPORT_SECRET_SUFFIX,
    _VM_DISK_PLURAL,
    _VM_GROUP,
    _VM_PLURAL,
    _VM_VERSION,
    _apply_namespaced_custom_object,
    _build_disk_manifest,
    _build_kube_api_client,
    _delete_namespaced_custom_object,
    _import_kubernetes_modules,
    _read_secret_payload,
    _resolve_image_source,
    _sanitize_name,
    _wait_for_deleted,
    _wait_for_disk_ready,
    _wait_for_vm_ready,
)
from log_redact import safe_log_fingerprint
from utils.crypto import derive_ssh_public_key, generate_ssh_keypair

logger = logging.getLogger(__name__)

_MANAGED_BY_LABEL = "shifter-provisioner"
_ATTACHMENT_MODE = "gdc-vmruntime-palo-alto-vmseries"
_PRODUCT = "palo-alto-vm-series"
_MGMT_INTERFACE_NAME = "eth0"
_DATA_INTERFACE_NAME = "eth1"
_SECRETMANAGER_MODULE = "google.cloud.secretmanager"
_GOOGLE_EXCEPTIONS_MODULE = "google.api_core.exceptions"
_INIT_CFG_FILENAME = "init-cfg.txt"
_BOOTSTRAP_XML_FILENAME = "bootstrap.xml"
_KEEP_FILENAME = ".keep"
_GCS_PREFIX = "gs://"


def _namespace_name(config: GDCPaloAltoVMSeriesConfig, user_id: int) -> str:
    return _sanitize_name(f"{config.namespace_prefix}-user-{user_id}")


def _resource_prefix(user_id: int, instance_id: str) -> str:
    instance_token = _sanitize_name(str(instance_id).split("-")[0], max_length=12)
    return _sanitize_name(f"ngfw-user-{user_id}-{instance_token}")


def _vm_name(user_id: int, instance_id: str) -> str:
    return _resource_prefix(user_id, instance_id)


def _boot_disk_name(vm_name: str) -> str:
    return _sanitize_name(f"{vm_name}-boot")


def _bootstrap_disk_name(vm_name: str) -> str:
    return _sanitize_name(f"{vm_name}-bootstrap")


def _ssh_secret_id(user_id: int, instance_id: str) -> str:
    environment = _sanitize_name(os.environ.get("ENVIRONMENT", "gcp-dev"), max_length=32)
    instance_token = str(instance_id).split("-")[0]
    return _sanitize_name(f"shifter-{environment}-ngfw-user-{user_id}-{instance_token}-ssh", max_length=255)


def _labels(*, user_id: int, request_id: str, instance_id: str) -> dict[str, str]:
    return {
        "app.kubernetes.io/managed-by": _MANAGED_BY_LABEL,
        "shifter.dev/component": "ngfw",
        "shifter.dev/product": _PRODUCT,
        "shifter.dev/range-plane": "gdc-vmruntime",
        "shifter.dev/user-id": str(user_id),
        "shifter.dev/request-id": str(request_id),
        "shifter.dev/instance-uuid": str(instance_id),
    }


def _ensure_namespace(core_api, namespace: str, labels: dict[str, str], api_exception) -> None:
    body = {"metadata": {"name": namespace, "labels": labels}}
    try:
        core_api.create_namespace(body=body)
        logger.info("Created GDC VM-Series namespace %s", namespace)
    except api_exception as exc:
        if exc.status != 409:
            raise
        core_api.patch_namespace(name=namespace, body={"metadata": {"labels": labels}})


def _ensure_ssh_secret(user_id: int, instance_id: str) -> tuple[str, str]:
    project_id = get_project_id()
    if not project_id:
        raise RuntimeError("GCP project ID is required to manage GDC VM-Series SSH secrets")

    secretmanager = import_google_module(_SECRETMANAGER_MODULE)
    google_exceptions = import_google_module(_GOOGLE_EXCEPTIONS_MODULE)
    client = secretmanager.SecretManagerServiceClient()
    secret_id = _ssh_secret_id(user_id, instance_id)
    full_secret_name = f"projects/{project_id}/secrets/{secret_id}"

    try:
        response = client.access_secret_version(request={"name": f"{full_secret_name}/versions/latest"})
        private_key = response.payload.data.decode("utf-8")
    except google_exceptions.NotFound:
        private_key, _public_key = generate_ssh_keypair()
        with contextlib_suppress(google_exceptions.AlreadyExists):
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


def _ensure_gcs_image_secret(
    core_api,
    client_module,
    namespace: str,
    config: GDCPaloAltoVMSeriesConfig,
    api_exception,
) -> str | None:
    if not config.image_gcs_secret_id:
        return None

    secret_data, _full_secret_name = _read_secret_payload(config.image_gcs_secret_id)
    body = client_module.V1Secret(
        metadata=client_module.V1ObjectMeta(name=_IMAGE_IMPORT_SECRET_SUFFIX, namespace=namespace),
        type="Opaque",
        string_data={"creds-gcp.json": secret_data},
    )
    try:
        core_api.create_namespaced_secret(namespace=namespace, body=body)
        logger.info(
            "Created GDC VM-Series image access secret ns_fp=%s/%s",
            safe_log_fingerprint(namespace),
            _IMAGE_IMPORT_SECRET_SUFFIX,
        )
    except api_exception as exc:
        if exc.status != 409:
            raise
        core_api.patch_namespaced_secret(name=_IMAGE_IMPORT_SECRET_SUFFIX, namespace=namespace, body=body)
        logger.info(
            "Updated GDC VM-Series image access secret ns_fp=%s/%s",
            safe_log_fingerprint(namespace),
            _IMAGE_IMPORT_SECRET_SUFFIX,
        )
    return _IMAGE_IMPORT_SECRET_SUFFIX


def _delete_ssh_secret(secret_ref: str) -> None:
    if not secret_ref:
        return
    secretmanager = import_google_module(_SECRETMANAGER_MODULE)
    google_exceptions = import_google_module(_GOOGLE_EXCEPTIONS_MODULE)
    client = secretmanager.SecretManagerServiceClient()
    try:
        client.delete_secret(request={"name": secret_ref})
        logger.info("Deleted GDC VM-Series SSH secret %s", secret_ref)
    except google_exceptions.NotFound:
        return


def _build_init_cfg(*, hostname: str, app_spec: dict[str, Any]) -> str:
    lines = [
        "type=dhcp-client",
        f"hostname={hostname}",
        "dns-primary=8.8.8.8",
        "dns-secondary=8.8.4.4",
        "panorama-server=cloud",
    ]
    scm_pin_id = str(app_spec.get("scm_pin_id", "")).strip()
    scm_pin_value = str(app_spec.get("scm_pin_value", "")).strip()
    scm_folder_name = str(app_spec.get("scm_folder_name", "")).strip()
    if scm_pin_id:
        lines.append(f"vm-series-auto-registration-pin-id={scm_pin_id}")
    if scm_pin_value:
        lines.append(f"vm-series-auto-registration-pin-value={scm_pin_value}")
    if scm_folder_name:
        lines.append(f"dgname={scm_folder_name}")
    return "\n".join(lines) + "\n"


def _render_bootstrap_xml(
    *,
    config: GDCPaloAltoVMSeriesConfig,
    public_key: str,
    hostname: str,
    app_spec: dict[str, Any],
) -> str:
    if not config.bootstrap_xml_template_secret_id:
        return ""

    template_text, _secret_name = _read_secret_payload(config.bootstrap_xml_template_secret_id)
    env = Environment(
        autoescape=select_autoescape(
            enabled_extensions=("html", "xml"),
            default_for_string=False,
            default=False,
        ),
    )
    template = env.from_string(template_text)
    return template.render(
        public_key=public_key,
        hostname=hostname,
        scm_pin_id=app_spec.get("scm_pin_id", ""),
        scm_pin_value=app_spec.get("scm_pin_value", ""),
        scm_folder_name=app_spec.get("scm_folder_name", ""),
        authcode=app_spec.get("authcode", ""),
    )


def _write_bootstrap_iso(
    *,
    iso_path: Path,
    init_cfg: str,
    authcode: str,
    bootstrap_xml: str,
) -> None:
    try:
        import pycdlib
    except ImportError as exc:
        raise RuntimeError(
            "GDC VM-Series bootstrap ISO generation requires pycdlib. "
            "Install the GCP provisioner extras from requirements-gcp.txt."
        ) from exc

    with tempfile.TemporaryDirectory(prefix="ngfw-bootstrap-") as temp_dir:
        temp_path = Path(temp_dir)
        config_dir = temp_path / "config"
        license_dir = temp_path / "license"
        content_dir = temp_path / "content"
        software_dir = temp_path / "software"
        for directory in (config_dir, license_dir, content_dir, software_dir):
            directory.mkdir()
        (config_dir / _INIT_CFG_FILENAME).write_text(init_cfg, encoding="utf-8")
        if bootstrap_xml:
            (config_dir / _BOOTSTRAP_XML_FILENAME).write_text(bootstrap_xml, encoding="utf-8")
        (license_dir / "authcodes").write_text(authcode, encoding="utf-8")
        (content_dir / _KEEP_FILENAME).write_text("", encoding="utf-8")
        (software_dir / _KEEP_FILENAME).write_text("", encoding="utf-8")

        iso = pycdlib.PyCdlib()
        try:
            iso.new(rock_ridge="1.09", vol_ident="PAN_BOOTSTRAP")
            for iso_dir, rr_name in (
                ("/CONFIG", "config"),
                ("/LICENSE", "license"),
                ("/CONTENT", "content"),
                ("/SOFTWARE", "software"),
            ):
                iso.add_directory(iso_dir, rr_name=rr_name)
            iso.add_file(str(config_dir / _INIT_CFG_FILENAME), "/CONFIG/INIT_CFG.TXT;1", rr_name=_INIT_CFG_FILENAME)
            if bootstrap_xml:
                iso.add_file(
                    str(config_dir / _BOOTSTRAP_XML_FILENAME),
                    "/CONFIG/BOOTSTRAP.XML;1",
                    rr_name=_BOOTSTRAP_XML_FILENAME,
                )
            iso.add_file(str(license_dir / "authcodes"), "/LICENSE/AUTHCODE.TXT;1", rr_name="authcodes")
            iso.add_file(str(content_dir / _KEEP_FILENAME), "/CONTENT/KEEP.TXT;1", rr_name=_KEEP_FILENAME)
            iso.add_file(str(software_dir / _KEEP_FILENAME), "/SOFTWARE/KEEP.TXT;1", rr_name=_KEEP_FILENAME)
            iso.write(str(iso_path))
        finally:
            iso.close()


def _upload_bootstrap_iso(
    *,
    config: GDCPaloAltoVMSeriesConfig,
    request_id: str,
    instance_id: str,
    iso_path: Path,
) -> str:
    storage = import_google_module("google.cloud.storage")
    client = storage.Client()
    key = f"bootstrap/ngfw/{instance_id}/bootstrap.iso"
    blob = client.bucket(config.bootstrap_bucket).blob(key)
    blob.upload_from_filename(str(iso_path), content_type="application/x-iso9660-image")
    logger.info("Uploaded GDC VM-Series bootstrap ISO to %s%s/%s", _GCS_PREFIX, config.bootstrap_bucket, key)
    del request_id
    return f"{_GCS_PREFIX}{config.bootstrap_bucket}/{key}"


def _delete_bootstrap_iso(bootstrap_gcs_url: str) -> None:
    if not bootstrap_gcs_url.startswith(_GCS_PREFIX):
        return
    storage = import_google_module("google.cloud.storage")
    google_exceptions = import_google_module(_GOOGLE_EXCEPTIONS_MODULE)
    bucket_and_key = bootstrap_gcs_url.removeprefix(_GCS_PREFIX)
    bucket_name, key = bucket_and_key.split("/", 1)
    try:
        storage.Client().bucket(bucket_name).blob(key).delete()
        logger.info("Deleted GDC VM-Series bootstrap ISO %s", bootstrap_gcs_url)
    except google_exceptions.NotFound:
        return


def _create_bootstrap_iso(
    *,
    config: GDCPaloAltoVMSeriesConfig,
    request_id: str,
    instance_id: str,
    hostname: str,
    app_spec: dict[str, Any],
    public_key: str,
) -> str:
    init_cfg = _build_init_cfg(hostname=hostname, app_spec=app_spec)
    bootstrap_xml = _render_bootstrap_xml(
        config=config,
        public_key=public_key,
        hostname=hostname,
        app_spec=app_spec,
    )
    with tempfile.TemporaryDirectory(prefix="ngfw-bootstrap-") as temp_dir:
        iso_path = Path(temp_dir) / "bootstrap.iso"
        _write_bootstrap_iso(
            iso_path=iso_path,
            init_cfg=init_cfg,
            authcode=str(app_spec.get("authcode", "")).strip(),
            bootstrap_xml=bootstrap_xml,
        )
        return _upload_bootstrap_iso(
            config=config,
            request_id=request_id,
            instance_id=instance_id,
            iso_path=iso_path,
        )


def _build_bootstrap_disk_manifest(
    *,
    namespace: str,
    disk_name: str,
    source_url: str,
    gcs_secret_name: str | None,
    disk_size_gib: int,
    storage_class_name: str,
    labels: dict[str, str],
) -> dict[str, Any]:
    manifest = {
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
            "diskType": "cdrom",
            "source": _resolve_image_source(source_url, gcs_secret_name),
        },
    }
    return manifest


def _interface_manifest(*, name: str, network_name: str, ip_cidr: str, default: bool) -> dict[str, Any]:
    interface = {
        "name": name,
        "networkName": network_name,
        "default": default,
    }
    if ip_cidr:
        interface["ipAddresses"] = [ip_cidr]
    return interface


def _build_vmseries_vm_manifest(
    *,
    namespace: str,
    vm_name: str,
    boot_disk_name: str,
    bootstrap_disk_name: str,
    config: GDCPaloAltoVMSeriesConfig,
    labels: dict[str, str],
) -> dict[str, Any]:
    return {
        "apiVersion": f"{_VM_GROUP}/{_VM_VERSION}",
        "kind": "VirtualMachine",
        "metadata": {
            "name": vm_name,
            "namespace": namespace,
            "labels": labels,
        },
        "spec": {
            "osType": "Linux",
            "compute": {
                "cpu": {"vcpus": config.vcpus},
                "memory": {"capacity": config.memory},
            },
            "interfaces": [
                _interface_manifest(
                    name=_MGMT_INTERFACE_NAME,
                    network_name=config.management_network_name,
                    ip_cidr=config.management_ip_cidr,
                    default=True,
                ),
                _interface_manifest(
                    name=_DATA_INTERFACE_NAME,
                    network_name=config.data_network_name,
                    ip_cidr=config.data_ip_cidr,
                    default=False,
                ),
            ],
            "disks": [
                {
                    "boot": True,
                    "autoDelete": False,
                    "virtualMachineDiskName": boot_disk_name,
                },
                {
                    "boot": False,
                    "autoDelete": False,
                    "virtualMachineDiskName": bootstrap_disk_name,
                },
            ],
        },
    }


def _ip_from_cidr(ip_cidr: str) -> str:
    return ip_cidr.split("/", 1)[0].strip() if ip_cidr else ""


def _extract_interface_ip(vm: dict[str, Any], interface_name: str) -> str:
    status = vm.get("status", {})
    for interface in status.get("interfaces", []) or []:
        if str(interface.get("name", "")).strip() != interface_name:
            continue
        for ip_address in interface.get("ipAddresses") or []:
            value = str(ip_address).strip()
            if value:
                return value.split("/", 1)[0]
    return ""


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

    boot_disk_manifest = _build_disk_manifest(
        namespace=namespace,
        disk_name=boot_disk_name,
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
        namespace=namespace,
        body=boot_disk_manifest,
        api_exception=api_exception,
    )
    _wait_for_disk_ready(custom_api, namespace, boot_disk_name, api_exception)

    bootstrap_disk_manifest = _build_bootstrap_disk_manifest(
        namespace=namespace,
        disk_name=bootstrap_disk_name,
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
        namespace=namespace,
        body=bootstrap_disk_manifest,
        api_exception=api_exception,
    )
    _wait_for_disk_ready(custom_api, namespace, bootstrap_disk_name, api_exception)

    vm_manifest = _build_vmseries_vm_manifest(
        namespace=namespace,
        vm_name=vm_name,
        boot_disk_name=boot_disk_name,
        bootstrap_disk_name=bootstrap_disk_name,
        config=config,
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

    vm = _wait_for_vm_ready(custom_api, namespace, vm_name, api_exception)
    management_ip = _ip_from_cidr(config.management_ip_cidr) or _extract_interface_ip(vm, _MGMT_INTERFACE_NAME)
    dataplane_ip = _ip_from_cidr(config.data_ip_cidr) or _extract_interface_ip(vm, _DATA_INTERFACE_NAME)
    if not management_ip:
        raise RuntimeError(f"GDC VM-Series {namespace}/{vm_name} reached running state without a management IP")

    data_attachment_id = f"{namespace}/{vm_name}:{_DATA_INTERFACE_NAME}"
    gcp_metadata = {
        "product": _PRODUCT,
        "namespace": namespace,
        "vm_name": vm_name,
        "boot_disk_name": boot_disk_name,
        "bootstrap_disk_name": bootstrap_disk_name,
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
        "gdc_namespace": namespace,
        "gdc_vm_name": vm_name,
        "gdc_boot_disk_name": boot_disk_name,
        "gdc_bootstrap_disk_name": bootstrap_disk_name,
        "gdc_bootstrap_gcs_url": bootstrap_gcs_url,
        "provider_metadata": {
            "gcp": gcp_metadata,
        },
    }


def _delete_vm_series_resource(
    custom_api,
    *,
    namespace: str,
    name: str,
    plural: str,
    label: str,
    api_exception,
) -> None:
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


def _delete_image_import_secret(core_api, namespace: str, api_exception) -> None:
    try:
        core_api.delete_namespaced_secret(name=_IMAGE_IMPORT_SECRET_SUFFIX, namespace=namespace)
    except api_exception as exc:
        if exc.status != 404:
            raise


def destroy_ngfw(state: dict[str, Any]) -> None:
    """Destroy a GDC VM Runtime Palo Alto VM-Series firewall and support assets."""
    access = load_gdc_network_access_config()
    if access is None:
        raise RuntimeError("GDC VM-Series destruction requires GDC_ACCESS_SECRET_ID")

    metadata = dict(state.get("provider_metadata", {}).get("gcp") or {})
    namespace = str(metadata.get("namespace") or state.get("gdc_namespace", "")).strip()
    vm_name = str(metadata.get("vm_name") or state.get("gdc_vm_name", "")).strip()
    boot_disk_name = str(metadata.get("boot_disk_name") or state.get("gdc_boot_disk_name", "")).strip()
    bootstrap_disk_name = str(metadata.get("bootstrap_disk_name") or state.get("gdc_bootstrap_disk_name", "")).strip()
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

    bootstrap_gcs_url = str(metadata.get("bootstrap_gcs_url") or state.get("gdc_bootstrap_gcs_url", "")).strip()
    _delete_bootstrap_iso(bootstrap_gcs_url)
    _delete_ssh_secret(str(metadata.get("ssh_key_secret_id") or state.get("ssh_key_secret_arn", "")).strip())
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


def contextlib_suppress(*exceptions):
    """Small wrapper to keep suppress local without shadowing test patches."""
    import contextlib

    return contextlib.suppress(*exceptions)
