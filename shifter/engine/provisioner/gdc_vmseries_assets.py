"""GCP resource builders for the GDC VM-Series NGFW lifecycle.

Extracted from ``gdc_vmseries_ngfw.py`` (Sonar S104). Builds the per-instance
GCP / Kubernetes resources — Secret Manager SSH + image-import secrets, the
bootstrap ISO (init-cfg + bootstrap.xml), and the VM / disk / interface
manifests — that the lifecycle orchestration in ``gdc_vmseries_ngfw`` applies.
``gdc_vmseries_ngfw`` re-imports these helpers so the bare call sites in
``apply_ngfw`` and the ``patch("gdc_vmseries_ngfw.X")`` test seams are unchanged.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jinja2 import Environment, select_autoescape

if TYPE_CHECKING:
    from types import ModuleType

    from kubernetes.client import CoreV1Api
    from kubernetes.client.exceptions import ApiException

from cloud.gcp.base import get_project_id, import_google_module
from config import (
    GDCPaloAltoVMSeriesConfig,
)
from gdc_vmruntime_assets import (
    _IMAGE_IMPORT_K8S_NAME,
    _VM_GROUP,
    _VM_VERSION,
    _read_secret_payload,
    _resolve_image_source,
)
from gdc_vmseries_common import (
    _BOOTSTRAP_XML_FILENAME,
    _DATA_INTERFACE_NAME,
    _GCS_PREFIX,
    _GOOGLE_EXCEPTIONS_MODULE,
    _INIT_CFG_FILENAME,
    _KEEP_FILENAME,
    _MGMT_INTERFACE_NAME,
    _SECRETMANAGER_MODULE,
    _ssh_secret_id,
    contextlib_suppress,
)
from log_redact import safe_log_fingerprint
from utils.crypto import derive_ssh_public_key, generate_ssh_keypair

logger = logging.getLogger(__name__)


def _ensure_namespace(
    core_api: CoreV1Api, namespace: str, labels: dict[str, str], api_exception: type[ApiException]
) -> None:
    """Create the VM-Series namespace, or patch its labels if it already exists."""
    body = {"metadata": {"name": namespace, "labels": labels}}
    try:
        core_api.create_namespace(body=body)
        logger.info("Created GDC VM-Series namespace %s", namespace)
    except api_exception as exc:
        if exc.status != 409:
            raise
        core_api.patch_namespace(name=namespace, body={"metadata": {"labels": labels}})


def _ensure_ssh_secret(user_id: int, instance_id: str) -> tuple[str, str]:
    """Fetch or create the VM-Series SSH keypair in Secret Manager.

    Returns the full secret resource name and the derived public key.
    """
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
    core_api: CoreV1Api,
    client_module: ModuleType,
    namespace: str,
    config: GDCPaloAltoVMSeriesConfig,
    api_exception: type[ApiException],
) -> str | None:
    """Create or update the namespaced secret that grants GCS image-pull access.

    Returns the secret name, or ``None`` when no image GCS secret is configured.
    """
    if not config.image_gcs_secret_id:
        return None

    secret_data, _full_secret_name = _read_secret_payload(config.image_gcs_secret_id)
    body = client_module.V1Secret(
        metadata=client_module.V1ObjectMeta(name=_IMAGE_IMPORT_K8S_NAME, namespace=namespace),
        type="Opaque",
        string_data={"creds-gcp.json": secret_data},
    )
    try:
        core_api.create_namespaced_secret(namespace=namespace, body=body)
        logger.info(
            "Created GDC VM-Series image access secret ns_fp=%s/%s",
            safe_log_fingerprint(namespace),
            _IMAGE_IMPORT_K8S_NAME,
        )
    except api_exception as exc:
        if exc.status != 409:
            raise
        core_api.patch_namespaced_secret(name=_IMAGE_IMPORT_K8S_NAME, namespace=namespace, body=body)
        logger.info(
            "Updated GDC VM-Series image access secret ns_fp=%s/%s",
            safe_log_fingerprint(namespace),
            _IMAGE_IMPORT_K8S_NAME,
        )
    return _IMAGE_IMPORT_K8S_NAME


def _delete_ssh_secret(secret_ref: str) -> None:
    """Delete the VM-Series SSH secret, ignoring an already-absent secret."""
    if not secret_ref:
        return
    secretmanager = import_google_module(_SECRETMANAGER_MODULE)
    google_exceptions = import_google_module(_GOOGLE_EXCEPTIONS_MODULE)
    client = secretmanager.SecretManagerServiceClient()
    try:
        client.delete_secret(request={"name": secret_ref})
        # secret_ref is a Secret Manager resource name; fingerprint it so the
        # delete is auditable without logging the secret path in clear text
        # (CodeQL py/clear-text-logging-sensitive-data).
        logger.info("Deleted GDC VM-Series SSH secret %s", safe_log_fingerprint(secret_ref))
    except google_exceptions.NotFound:
        return


def _build_init_cfg(*, hostname: str, app_spec: dict[str, Any]) -> str:
    """Render the PAN-OS ``init-cfg.txt`` bootstrap content for the firewall."""
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
    """Render the optional ``bootstrap.xml`` from its Jinja template secret.

    Returns an empty string when no bootstrap-XML template is configured.
    """
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
    """Write the PAN-OS bootstrap ISO9660 image to ``iso_path``.

    Requires the optional ``pycdlib`` GCP provisioner extra.
    """
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
    """Upload the bootstrap ISO to the configured GCS bucket and return its URL."""
    storage = import_google_module("google.cloud.storage")
    client = storage.Client()
    key = f"bootstrap/ngfw/{instance_id}/bootstrap.iso"
    blob = client.bucket(config.bootstrap_bucket).blob(key)
    blob.upload_from_filename(str(iso_path), content_type="application/x-iso9660-image")
    logger.info("Uploaded GDC VM-Series bootstrap ISO to %s%s/%s", _GCS_PREFIX, config.bootstrap_bucket, key)
    del request_id
    return f"{_GCS_PREFIX}{config.bootstrap_bucket}/{key}"


def _delete_bootstrap_iso(bootstrap_gcs_url: str) -> None:
    """Delete the bootstrap ISO from GCS, ignoring an already-absent object."""
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
    """Build the bootstrap ISO and upload it to GCS, returning its URL."""
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
    """Build the VirtualMachineDisk manifest for the bootstrap (cdrom) disk."""
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
    """Build one VirtualMachine network-interface manifest entry."""
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
    """Build the VirtualMachine manifest with mgmt/data interfaces and disks."""
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
    """Return the bare IP address from a ``ip/prefix`` CIDR string."""
    return ip_cidr.split("/", 1)[0].strip() if ip_cidr else ""


def _extract_interface_ip(vm: dict[str, Any], interface_name: str) -> str:
    """Return the first IP reported for ``interface_name`` in the VM status."""
    status = vm.get("status", {})
    for interface in status.get("interfaces", []) or []:
        if str(interface.get("name", "")).strip() != interface_name:
            continue
        for ip_address in interface.get("ipAddresses") or []:
            value = str(ip_address).strip()
            if value:
                return value.split("/", 1)[0]
    return ""
