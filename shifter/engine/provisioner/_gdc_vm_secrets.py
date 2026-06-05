"""Secret-Manager and Kubernetes secret management for GDC VM Runtime guests.

Covers:
- Per-instance SSH keypair secrets (``-ssh`` suffix)
- Per-instance RDP password secrets (``-rdp-password`` suffix, non-DC only)
- The shared per-namespace GCS image-pull credential secret
- Reading arbitrary GCP Secret Manager payloads
"""

from __future__ import annotations

import logging
from contextlib import suppress
from types import ModuleType
from typing import TYPE_CHECKING, Any

from _gdc_vm_naming import _build_instance_secret_name
from cloud.gcp.base import get_project_id, import_google_module
from config import GDCVMRuntimeConfig
from log_redact import safe_log_fingerprint
from utils.crypto import derive_ssh_public_key, generate_rdp_password, generate_ssh_keypair

if TYPE_CHECKING:
    from kubernetes.client import CoreV1Api
    from kubernetes.client.exceptions import ApiException

logger = logging.getLogger(__name__)

_IMAGE_IMPORT_K8S_NAME = "-".join(("gdc", "vm", "image", "gcs"))
_SECRETMANAGER_MODULE = "google.cloud.secretmanager"
_GOOGLE_EXCEPTIONS_MODULE = "google.api_core.exceptions"


def _read_secret_payload(secret_id: str) -> tuple[str, str]:
    """Read the latest GCP Secret Manager payload for ``secret_id``."""
    secretmanager = import_google_module(_SECRETMANAGER_MODULE)
    client = secretmanager.SecretManagerServiceClient()
    if secret_id.startswith("projects/"):
        full_secret_name = secret_id
    else:
        full_secret_name = f"projects/{get_project_id()}/secrets/{secret_id}"
    response = client.access_secret_version(request={"name": f"{full_secret_name}/versions/latest"})
    return response.payload.data.decode("utf-8"), full_secret_name


def _ensure_ssh_secret(range_id: int, instance: dict[str, Any]) -> tuple[str, str]:
    """Create-or-read the per-instance SSH key secret and return its reference and public key."""
    project_id = get_project_id()
    if not project_id:
        raise RuntimeError("GCP project ID is required to manage GDC VM Runtime SSH secrets")

    secretmanager = import_google_module(_SECRETMANAGER_MODULE)
    google_exceptions = import_google_module(_GOOGLE_EXCEPTIONS_MODULE)
    client = secretmanager.SecretManagerServiceClient()
    secret_id = _build_instance_secret_name(range_id, instance, kind="ssh")
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
    """Delete the per-instance SSH key secret, ignoring NotFound."""
    project_id = get_project_id()
    if not project_id:
        return

    secretmanager = import_google_module(_SECRETMANAGER_MODULE)
    google_exceptions = import_google_module(_GOOGLE_EXCEPTIONS_MODULE)
    client = secretmanager.SecretManagerServiceClient()
    secret_name = f"projects/{project_id}/secrets/{_build_instance_secret_name(range_id, instance, kind='ssh')}"
    try:
        client.delete_secret(request={"name": secret_name})
        logger.info("Deleted GDC SSH secret secret_fp=%s", safe_log_fingerprint(secret_name))
    except google_exceptions.NotFound:
        return


def _ensure_rdp_password_secret(range_id: int, instance: dict[str, Any]) -> tuple[str, str]:
    """Create or read a per-instance RDP password (GCP Secret Manager) (#762).

    Idempotent: on repeated runs (e.g., resume after a transient
    failure) the existing secret's value is returned so the guest's
    chpasswd / net-user step keeps using the same value across boots.
    Returns a tuple of ``(secret_ref, password_value)``.
    """
    project_id = get_project_id()
    if not project_id:
        raise RuntimeError("GCP project ID is required to manage GDC VM Runtime RDP password secrets")

    secretmanager = import_google_module(_SECRETMANAGER_MODULE)
    google_exceptions = import_google_module(_GOOGLE_EXCEPTIONS_MODULE)
    client = secretmanager.SecretManagerServiceClient()
    secret_id = _build_instance_secret_name(range_id, instance, kind="rdp-password")
    full_secret_name = f"projects/{project_id}/secrets/{secret_id}"

    try:
        response = client.access_secret_version(request={"name": f"{full_secret_name}/versions/latest"})
        password = response.payload.data.decode("utf-8")
    except google_exceptions.NotFound:
        password = generate_rdp_password()
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
                "payload": {"data": password.encode("utf-8")},
            }
        )

    return full_secret_name, password


def _delete_rdp_password_secret(range_id: int, instance: dict[str, Any]) -> None:
    """Delete the per-instance RDP password secret, ignoring NotFound."""
    project_id = get_project_id()
    if not project_id:
        return

    secretmanager = import_google_module(_SECRETMANAGER_MODULE)
    google_exceptions = import_google_module(_GOOGLE_EXCEPTIONS_MODULE)
    client = secretmanager.SecretManagerServiceClient()
    secret_name = (
        f"projects/{project_id}/secrets/{_build_instance_secret_name(range_id, instance, kind='rdp-password')}"
    )
    try:
        client.delete_secret(request={"name": secret_name})
        logger.info("Deleted GDC RDP password secret secret_fp=%s", safe_log_fingerprint(secret_name))
    except google_exceptions.NotFound:
        return


def _ensure_gcs_image_secret(
    core_api: CoreV1Api,
    client_module: ModuleType,
    namespace: str,
    vm_config: GDCVMRuntimeConfig,
    api_exception: type[ApiException],
) -> str | None:
    """Create-or-patch the GCS image-pull Kubernetes secret if one is configured."""
    if not vm_config.image_gcs_secret_id:
        return None

    secret_data, _full_secret_name = _read_secret_payload(vm_config.image_gcs_secret_id)
    body = client_module.V1Secret(
        metadata=client_module.V1ObjectMeta(name=_IMAGE_IMPORT_K8S_NAME, namespace=namespace),
        type="Opaque",
        string_data={"creds-gcp.json": secret_data},
    )
    try:
        core_api.create_namespaced_secret(namespace=namespace, body=body)
        logger.info(
            "Created GDC VM image access secret ns_fp=%s/%s",
            safe_log_fingerprint(namespace),
            _IMAGE_IMPORT_K8S_NAME,
        )
    except api_exception as exc:
        if exc.status != 409:
            raise
        core_api.patch_namespaced_secret(name=_IMAGE_IMPORT_K8S_NAME, namespace=namespace, body=body)
        logger.info(
            "Updated GDC VM image access secret ns_fp=%s/%s",
            safe_log_fingerprint(namespace),
            _IMAGE_IMPORT_K8S_NAME,
        )
    return _IMAGE_IMPORT_K8S_NAME
