"""Canonical identities and migration locations for GCP range secrets.

Dynamic range credentials belong to one deployment-scoped Secret Manager
project.  During rollout that project may intentionally equal the platform
project; in that compatibility state the legacy ids remain authoritative.
After the projects split, existing legacy secrets are read first, new secrets
are created only under canonical ids in the dedicated project, and teardown
checks both exact locations.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum, auto
from typing import Protocol

_MAX_SECRET_ID_LENGTH = 255
_ENVIRONMENT_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class DynamicSecretPublicationPending(RuntimeError):
    """An existing Secret container has no version published yet."""


class DynamicSecretClass(StrEnum):
    """Closed credential classes whose authorization audience is centrally owned."""

    GCE_HOST_SSH = auto()
    GCE_PARTICIPANT_SSH = auto()
    GCE_RDP_PASSWORD = auto()
    RAES_HOST_SSH = auto()
    RAES_ACCOUNT_PASSWORD = auto()
    RAES_ACCOUNT_PUBLIC_KEY = auto()
    RAES_DOMAIN_DSRM_PASSWORD = auto()
    RAES_DOMAIN_AUTHORITY_PASSWORD = auto()
    RAES_DOMAIN_ACCOUNT_PASSWORD = auto()
    GDC_VM_SSH = auto()
    GDC_VM_RDP_PASSWORD = auto()
    VMSERIES_SSH = auto()
    VERTEX_SERVICE_ACCOUNT_KEY = auto()
    VPN_ISSUER = auto()
    VPN_SERVER = auto()
    VPN_PROFILE = auto()


@dataclass(frozen=True)
class _DynamicSecretNameClass:
    """Stable family and purpose fragments for one credential class."""

    family: str
    purpose: str


_DYNAMIC_SECRET_NAME_CLASSES = {
    DynamicSecretClass.GCE_HOST_SSH: _DynamicSecretNameClass("gce", "ssh"),
    DynamicSecretClass.GCE_PARTICIPANT_SSH: _DynamicSecretNameClass("gce", "ssh"),
    DynamicSecretClass.GCE_RDP_PASSWORD: _DynamicSecretNameClass("gce", "rdp-password"),
    DynamicSecretClass.RAES_HOST_SSH: _DynamicSecretNameClass("raes", "ssh"),
    DynamicSecretClass.RAES_ACCOUNT_PASSWORD: _DynamicSecretNameClass("raes", "account-password"),
    DynamicSecretClass.RAES_ACCOUNT_PUBLIC_KEY: _DynamicSecretNameClass("raes", "account-publickey"),
    DynamicSecretClass.RAES_DOMAIN_DSRM_PASSWORD: _DynamicSecretNameClass("raes", "dsrm-password"),
    DynamicSecretClass.RAES_DOMAIN_AUTHORITY_PASSWORD: _DynamicSecretNameClass("raes", "authority-password"),
    DynamicSecretClass.RAES_DOMAIN_ACCOUNT_PASSWORD: _DynamicSecretNameClass("raes", "account-password"),
    DynamicSecretClass.GDC_VM_SSH: _DynamicSecretNameClass("gdc-vm", "ssh"),
    DynamicSecretClass.GDC_VM_RDP_PASSWORD: _DynamicSecretNameClass("gdc-vm", "rdp-password"),
    DynamicSecretClass.VMSERIES_SSH: _DynamicSecretNameClass("vmseries", "ssh"),
    DynamicSecretClass.VERTEX_SERVICE_ACCOUNT_KEY: _DynamicSecretNameClass("vertex", "service-account-key"),
    DynamicSecretClass.VPN_ISSUER: _DynamicSecretNameClass("vpn", "issuer"),
    DynamicSecretClass.VPN_SERVER: _DynamicSecretNameClass("vpn", "server"),
    DynamicSecretClass.VPN_PROFILE: _DynamicSecretNameClass("vpn", "profile"),
}

_PARTICIPANT_SECRET_CLASSES = frozenset(
    {
        DynamicSecretClass.GCE_PARTICIPANT_SSH,
        DynamicSecretClass.GCE_RDP_PASSWORD,
        DynamicSecretClass.RAES_ACCOUNT_PASSWORD,
        DynamicSecretClass.RAES_ACCOUNT_PUBLIC_KEY,
        DynamicSecretClass.GDC_VM_SSH,
        DynamicSecretClass.GDC_VM_RDP_PASSWORD,
        DynamicSecretClass.VMSERIES_SSH,
        DynamicSecretClass.VPN_PROFILE,
    }
)


def _sanitize(value: object) -> str:
    """Normalize a value into a non-empty Secret Manager name fragment."""
    normalized = re.sub(r"[^a-z0-9-]+", "-", str(value).strip().lower())
    return re.sub(r"-{2,}", "-", normalized).strip("-") or "unknown"


def _deployment_environment(environment: str | None) -> str:
    """Resolve the exact deployment namespace used by the IAM prefix."""
    if environment is None:
        configured = os.environ.get("ENVIRONMENT")
        if configured is None or not configured.strip():
            raise RuntimeError("ENVIRONMENT is required to build canonical GCP dynamic-secret names")
    else:
        configured = environment
    deployment = configured.strip()
    if deployment != configured or not _ENVIRONMENT_RE.fullmatch(deployment):
        raise ValueError("dynamic-secret environment must be lowercase alphanumeric words separated by single hyphens")
    return deployment


def canonical_secret_id(
    *,
    credential_class: DynamicSecretClass,
    scope: str,
    environment: str | None = None,
) -> str:
    """Return a canonical ID using the centrally classified authorization audience."""
    if not isinstance(credential_class, DynamicSecretClass):
        raise ValueError(f"unsupported dynamic-secret credential class {credential_class!r}")
    name_class = _DYNAMIC_SECRET_NAME_CLASSES[credential_class]
    audience = "participant" if credential_class in _PARTICIPANT_SECRET_CLASSES else "workload"
    deployment = _deployment_environment(environment)
    identity = "-".join(
        (
            "shifter",
            _sanitize(deployment),
            "dynamic",
            audience,
            name_class.family,
            _sanitize(scope),
            name_class.purpose,
        )
    )
    if len(identity) <= _MAX_SECRET_ID_LENGTH:
        return identity
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return f"{identity[: _MAX_SECRET_ID_LENGTH - len(digest) - 1].rstrip('-')}-{digest}"


def dynamic_secret_project_id() -> str:
    """Resolve the explicitly configured dynamic-secret project.

    A compatibility deployment may explicitly set this to ``platform_project_id``.
    Omission is never compatibility intent: silently substituting the platform
    project would redirect new credential writes across the security boundary.
    """
    dynamic_project_id = os.environ.get("GCP_DYNAMIC_SECRET_PROJECT_ID", "").strip()
    if not dynamic_project_id:
        raise RuntimeError(
            "GCP_DYNAMIC_SECRET_PROJECT_ID is required to manage dynamic range secrets; "
            "set it explicitly to the platform project only during staged migration"
        )
    return dynamic_project_id


def secret_ref(project_id: str, secret_id: str) -> str:
    """Build an exact Secret Manager resource name."""
    if not project_id:
        raise RuntimeError("GCP project ID is required to manage dynamic range secrets")
    return f"projects/{project_id}/secrets/{secret_id}"


@dataclass(frozen=True)
class SecretLocations:
    """Exact read/create/delete locations across the rollout boundary."""

    read_refs: tuple[str, ...]
    create_ref: str
    delete_refs: tuple[str, ...]


@dataclass(frozen=True)
class SecretRetrySettings:
    """Bounded waits used while creating and publishing a dynamic secret."""

    concurrent_read_attempts: int = 5
    concurrent_read_delay_seconds: float = 0.1
    version_add_attempts: int = 3
    version_add_delay_seconds: float = 0.1


_DEFAULT_RETRY_SETTINGS = SecretRetrySettings()


class _SecretPayload(Protocol):
    """Secret Manager payload subset used by this module."""

    data: bytes


class _SecretVersion(Protocol):
    """Secret Manager version subset used by this module."""

    payload: _SecretPayload


class SecretManagerClient(Protocol):
    """Secret Manager client operations required by the lifecycle helpers."""

    def access_secret_version(self, *, request: dict[str, object]) -> _SecretVersion:
        """Read one secret version."""

    def get_secret(self, *, request: dict[str, object]) -> object:
        """Read one secret container."""

    def create_secret(self, *, request: dict[str, object]) -> object:
        """Create one secret container."""

    def add_secret_version(self, *, request: dict[str, object]) -> object:
        """Publish one secret value."""

    def delete_secret(self, *, request: dict[str, object]) -> object:
        """Delete one secret container."""


class GoogleSecretExceptions(Protocol):
    """Google exception classes required by the lifecycle helpers."""

    NotFound: type[Exception]
    AlreadyExists: type[Exception]


def secret_locations(
    *,
    platform_project_id: str,
    dynamic_project_id: str,
    legacy_secret_id: str,
    canonical_secret_id: str,
) -> SecretLocations:
    """Return migration-aware locations without permitting fallback creation."""
    legacy_ref = secret_ref(platform_project_id, legacy_secret_id)
    if dynamic_project_id == platform_project_id:
        return SecretLocations(read_refs=(legacy_ref,), create_ref=legacy_ref, delete_refs=(legacy_ref,))
    canonical_ref = secret_ref(dynamic_project_id, canonical_secret_id)
    refs = (legacy_ref, canonical_ref)
    return SecretLocations(read_refs=refs, create_ref=canonical_ref, delete_refs=refs)


def read_or_create(
    client: SecretManagerClient,
    exceptions: GoogleSecretExceptions,
    locations: SecretLocations,
    payload_factory: Callable[[], str],
    *,
    retry_settings: SecretRetrySettings = _DEFAULT_RETRY_SETTINGS,
) -> tuple[str, str]:
    """Resolve legacy/canonical state without racing an in-flight creator."""
    existing = read_published_or_wait(
        client,
        exceptions,
        locations.read_refs,
        attempts=retry_settings.concurrent_read_attempts,
        delay_seconds=retry_settings.concurrent_read_delay_seconds,
    )
    if existing is not None:
        return existing

    name = locations.create_ref
    parent, created_secret_id = name.rsplit("/secrets/", 1)
    try:
        client.create_secret(
            request={
                "parent": parent,
                "secret_id": created_secret_id,
                "secret": {"replication": {"automatic": {}}},
            }
        )
    except exceptions.AlreadyExists:
        return name, wait_for_published_value(
            client,
            exceptions,
            name,
            attempts=retry_settings.concurrent_read_attempts,
            delay_seconds=retry_settings.concurrent_read_delay_seconds,
        )
    # Generate credentials only after this process created the container. An
    # existing empty container belongs to an in-flight or failed writer and is
    # handled by the bounded wait above rather than receiving a rival value.
    value = payload_factory()
    retryable_type_list: list[type[BaseException]] = []
    for exception_name in ("DeadlineExceeded", "InternalServerError", "ServiceUnavailable", "TooManyRequests"):
        exception_type = getattr(exceptions, exception_name, None)
        if isinstance(exception_type, type) and issubclass(exception_type, BaseException):
            retryable_type_list.append(exception_type)
    retryable_types = tuple(retryable_type_list)
    for attempt in range(retry_settings.version_add_attempts):
        try:
            client.add_secret_version(request={"parent": name, "payload": {"data": value.encode("utf-8")}})
            break
        except retryable_types:
            if attempt == retry_settings.version_add_attempts - 1:
                raise
            time.sleep(retry_settings.version_add_delay_seconds)
    return name, value


def read_published_or_wait(
    client: SecretManagerClient,
    exceptions: GoogleSecretExceptions,
    names: tuple[str, ...],
    *,
    attempts: int = 5,
    delay_seconds: float = 0.1,
) -> tuple[str, str] | None:
    """Read the first published value, waiting if any exact container is empty."""
    for name in names:
        try:
            response = client.access_secret_version(request={"name": f"{name}/versions/latest"})
            return name, response.payload.data.decode("utf-8")
        except exceptions.NotFound:
            try:
                client.get_secret(request={"name": name})
            except exceptions.NotFound:
                continue
            return name, wait_for_published_value(
                client,
                exceptions,
                name,
                attempts=attempts,
                delay_seconds=delay_seconds,
            )
    return None


def wait_for_published_value(
    client: SecretManagerClient,
    exceptions: GoogleSecretExceptions,
    name: str,
    *,
    attempts: int = 5,
    delay_seconds: float = 0.1,
) -> str:
    """Wait for the creator of an existing container without publishing a rival value."""
    for attempt in range(attempts):
        try:
            response = client.access_secret_version(request={"name": f"{name}/versions/latest"})
            return response.payload.data.decode("utf-8")
        except exceptions.NotFound:
            if attempt < attempts - 1:
                time.sleep(delay_seconds)
    raise DynamicSecretPublicationPending(
        "dynamic secret creation is still pending; retry after the original creator "
        "publishes or the empty container is removed"
    ) from None


def delete_all(client: SecretManagerClient, exceptions: GoogleSecretExceptions, locations: SecretLocations) -> None:
    """Delete every exact migration location, ignoring already-absent secrets."""
    for name in locations.delete_refs:
        try:
            client.delete_secret(request={"name": name})
        except exceptions.NotFound:
            continue
