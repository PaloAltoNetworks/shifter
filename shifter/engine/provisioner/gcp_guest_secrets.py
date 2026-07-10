"""GCP Secret Manager helpers for range guest credentials."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from contextlib import suppress
from typing import Protocol

from cloud.gcp.base import get_project_id, import_google_module
from log_redact import safe_log_fingerprint
from utils.crypto import derive_ssh_public_key, generate_rdp_password, generate_ssh_keypair

logger = logging.getLogger(__name__)

_SECRETMANAGER_MODULE = "google.cloud.secretmanager"
_GOOGLE_EXCEPTIONS_MODULE = "google.api_core.exceptions"
GuestInstance = dict[str, object]


class _SecretPayload(Protocol):
    """Secret Manager payload subset used by credential reads."""

    data: bytes


class _SecretVersionResponse(Protocol):
    """Secret Manager version response subset used by credential reads."""

    payload: _SecretPayload


class _SecretManagerClient(Protocol):
    """Secret Manager client subset used by guest credential helpers."""

    def access_secret_version(self, *, request: dict[str, object]) -> _SecretVersionResponse:
        """Return the latest secret version."""

    def create_secret(self, *, request: dict[str, object]) -> object:
        """Create a Secret Manager secret."""

    def add_secret_version(self, *, request: dict[str, object]) -> object:
        """Add a Secret Manager secret version."""

    def delete_secret(self, *, request: dict[str, object]) -> object:
        """Delete a Secret Manager secret."""


class _GoogleExceptions(Protocol):
    """Google exception module subset used by secret helpers."""

    NotFound: type[Exception]
    AlreadyExists: type[Exception]


def _sanitize_secret_part(value: str, *, max_length: int = 48) -> str:
    """Normalize part of a Secret Manager secret id."""
    normalized = re.sub(r"[^a-z0-9-]+", "-", value.strip().lower())
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    return normalized[:max_length].rstrip("-") or "guest"


def _guest_secret_id(range_id: int, instance: GuestInstance, kind: str) -> str:
    """Return the deterministic secret id for a range guest credential."""
    instance_part = str(instance.get("uuid") or instance.get("name") or instance.get("role") or "guest")
    return _sanitize_secret_part(f"shifter-range-{range_id}-{instance_part}-{kind}", max_length=255)


def _secret_client() -> tuple[_SecretManagerClient, _GoogleExceptions, str]:
    """Build the Secret Manager client and resolve the active project id."""
    project_id = get_project_id()
    if not project_id:
        raise RuntimeError("GCP project ID is required to manage range guest secrets")
    secretmanager = import_google_module(_SECRETMANAGER_MODULE)
    google_exceptions = import_google_module(_GOOGLE_EXCEPTIONS_MODULE)
    return secretmanager.SecretManagerServiceClient(), google_exceptions, project_id


def _read_or_create_secret(secret_id: str, payload_factory: Callable[[], str]) -> tuple[str, str]:
    """Read the latest secret value or create it from the supplied factory."""
    client, google_exceptions, project_id = _secret_client()
    secret_name = f"projects/{project_id}/secrets/{secret_id}"
    try:
        response = client.access_secret_version(request={"name": f"{secret_name}/versions/latest"})
        value = response.payload.data.decode("utf-8")
    except google_exceptions.NotFound:
        value = payload_factory()
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
                "parent": secret_name,
                "payload": {"data": value.encode("utf-8")},
            }
        )
    return secret_name, value


def ensure_ssh_secret(range_id: int, instance: GuestInstance) -> tuple[str, str]:
    """Create or read a per-instance SSH private key secret."""
    secret_name, private_key = _read_or_create_secret(
        _guest_secret_id(range_id, instance, "ssh"),
        lambda: generate_ssh_keypair()[0],
    )
    return secret_name, derive_ssh_public_key(private_key)


def ensure_rdp_password_secret(range_id: int, instance: GuestInstance) -> tuple[str, str]:
    """Create or read a per-instance local password secret."""
    return _read_or_create_secret(
        _guest_secret_id(range_id, instance, "rdp-password"),
        generate_rdp_password,
    )


def delete_guest_secret(range_id: int, instance: GuestInstance, kind: str) -> None:
    """Delete a per-instance guest secret, ignoring missing secrets."""
    try:
        client, google_exceptions, project_id = _secret_client()
    except RuntimeError:
        return
    secret_name = f"projects/{project_id}/secrets/{_guest_secret_id(range_id, instance, kind)}"
    try:
        client.delete_secret(request={"name": secret_name})
        logger.info("Deleted GCP range guest secret secret_fp=%s", safe_log_fingerprint(secret_name))
    except google_exceptions.NotFound:
        return


def delete_ssh_secret(range_id: int, instance: GuestInstance) -> None:
    """Delete the per-instance SSH secret."""
    delete_guest_secret(range_id, instance, "ssh")


def delete_rdp_password_secret(range_id: int, instance: GuestInstance) -> None:
    """Delete the per-instance password secret."""
    delete_guest_secret(range_id, instance, "rdp-password")
