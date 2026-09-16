"""GCP Secret Manager helpers for range guest credentials."""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable
from typing import Protocol

from cloud.gcp.base import get_project_id, import_google_module
from gcp_dynamic_secrets import (
    DynamicSecretClass,
    canonical_secret_id,
    delete_all,
    dynamic_secret_project_id,
    read_or_create,
    secret_locations,
)
from log_redact import safe_log_fingerprint
from utils.crypto import derive_ssh_public_key, generate_rdp_password, generate_ssh_keypair

logger = logging.getLogger(__name__)

_SECRETMANAGER_MODULE = "google.cloud.secretmanager"
_GOOGLE_EXCEPTIONS_MODULE = "google.api_core.exceptions"
GuestInstance = dict[str, object]

_RAES_PASSWORD_LENGTHS = {"weak": 12, "medium": 18, "strong": 24}
_RAES_ACCOUNT_SECRET_KINDS = {
    "password": "-".join(("account", "password")),
    "key": "account-publickey",
}


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

    def get_secret(self, *, request: dict[str, object]) -> object:
        """Return an existing secret container."""

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
    """Build the Secret Manager client and resolve the platform project id."""
    project_id = get_project_id()
    if not project_id:
        raise RuntimeError("GCP project ID is required to manage range guest secrets")
    secretmanager = import_google_module(_SECRETMANAGER_MODULE)
    google_exceptions = import_google_module(_GOOGLE_EXCEPTIONS_MODULE)
    return secretmanager.SecretManagerServiceClient(), google_exceptions, project_id


def _read_or_create_secret(
    secret_id: str,
    payload_factory: Callable[[], str],
    canonical_id: str | None = None,
) -> tuple[str, str]:
    """Read an exact legacy/canonical value or create only in the target project."""
    client, google_exceptions, platform_project_id = _secret_client()
    locations = secret_locations(
        platform_project_id=platform_project_id,
        dynamic_project_id=dynamic_secret_project_id(),
        legacy_secret_id=secret_id,
        canonical_secret_id=canonical_id or secret_id,
    )
    return read_or_create(client, google_exceptions, locations, payload_factory)


def _canonical_guest_secret_id(
    range_id: int,
    instance: GuestInstance,
    kind: str,
) -> str:
    """Return the centrally classified canonical id for a GCE guest credential."""
    instance_part = str(instance.get("uuid") or instance.get("name") or instance.get("role") or "guest")
    credential_class = {
        "ssh": DynamicSecretClass.GCE_HOST_SSH,
        "participant-ssh": DynamicSecretClass.GCE_PARTICIPANT_SSH,
        "rdp-password": DynamicSecretClass.GCE_RDP_PASSWORD,
    }.get(kind)
    if credential_class is None:
        raise ValueError(f"unsupported GCE guest secret kind {kind!r}")
    return canonical_secret_id(
        credential_class=credential_class,
        scope=f"range-{range_id}-{instance_part}",
    )


def ensure_ssh_secret(range_id: int, instance: GuestInstance) -> tuple[str, str]:
    """Create or read a per-instance SSH private key secret."""
    secret_name, private_key = _read_or_create_secret(
        _guest_secret_id(range_id, instance, "ssh"),
        lambda: generate_ssh_keypair()[0],
        _canonical_guest_secret_id(range_id, instance, "ssh"),
    )
    return secret_name, derive_ssh_public_key(private_key)


def ensure_participant_ssh_secret(range_id: int, instance: GuestInstance) -> tuple[str, str]:
    """Create/read a participant key distinct from the host-management key."""
    secret_name, private_key = _read_or_create_secret(
        _guest_secret_id(range_id, instance, "participant-ssh"),
        lambda: generate_ssh_keypair()[0],
        _canonical_guest_secret_id(range_id, instance, "participant-ssh"),
    )
    return secret_name, derive_ssh_public_key(private_key)


def ensure_rdp_password_secret(range_id: int, instance: GuestInstance) -> tuple[str, str]:
    """Create or read a per-instance local password secret."""
    return _read_or_create_secret(
        _guest_secret_id(range_id, instance, "rdp-password"),
        generate_rdp_password,
        _canonical_guest_secret_id(range_id, instance, "rdp-password"),
    )


def _raes_secret_id(range_id: int, instance_key: str, kind: str) -> str:
    """Return the deterministic secret id for an RAES-native range instance.

    Keyed on the range id + the RAES instance key (node address + count index),
    not a cyberscript ``ScenarioInstance``: the RAES provisioning path carries no
    scenario role/os enums, so credentials are minted per authored node instance.
    """
    return _sanitize_secret_part(f"shifter-range-{range_id}-raes-{instance_key}-{kind}", max_length=255)


def ensure_raes_ssh_secret(range_id: int, instance_key: str) -> tuple[str, str]:
    """Create or read the provisioner-managed SSH key for one RAES range instance.

    The provisioner owns this range-management credential (it is not a participant
    account, which is a later participant-runtime concern): it mints the keypair,
    stores the private half in Secret Manager, and returns ``(secret_ref,
    public_key)`` so the public half can be injected as the guest login key.
    """
    secret_name, private_key = _read_or_create_secret(
        _raes_secret_id(range_id, instance_key, "ssh"),
        lambda: generate_ssh_keypair()[0],
        canonical_secret_id(
            credential_class=DynamicSecretClass.RAES_HOST_SSH,
            scope=f"range-{range_id}-{instance_key}",
        ),
    )
    return secret_name, derive_ssh_public_key(private_key)


def _raes_account_secret_id(range_id: int, instance_key: str, username: str, kind: str) -> str:
    """Return a collision-resistant deterministic authored-account secret id."""
    user_digest = hashlib.sha256(username.encode("utf-8")).hexdigest()[:40]
    user_part = _sanitize_secret_part(username, max_length=32)
    suffix = f"{user_part}-{user_digest}-{kind}"
    prefix = _sanitize_secret_part(f"shifter-range-{range_id}-raes-{instance_key}", max_length=254 - len(suffix))
    return f"{prefix}-{suffix}"


def _canonical_raes_account_secret_id(range_id: int, instance_key: str, username: str, purpose: str) -> str:
    """Return the canonical workload id without exposing the authored username."""
    user_digest = hashlib.sha256(username.encode("utf-8")).hexdigest()[:40]
    credential_class = {
        "account-password": DynamicSecretClass.RAES_ACCOUNT_PASSWORD,
        "account-publickey": DynamicSecretClass.RAES_ACCOUNT_PUBLIC_KEY,
    }.get(purpose)
    if credential_class is None:
        raise ValueError(f"unsupported RAES account secret purpose {purpose!r}")
    return canonical_secret_id(
        credential_class=credential_class,
        scope=f"range-{range_id}-{instance_key}-{user_digest}",
    )


def _raes_directory_secret_id(range_id: int, domain_id: str, subject_address: str, purpose: str) -> str:
    """Return an opaque deterministic id for one range-local directory secret."""
    identity = "\0".join((str(range_id), domain_id, subject_address, purpose)).encode("utf-8")
    digest = hashlib.sha256(identity).hexdigest()[:40]
    safe_purpose = _sanitize_secret_part(purpose, max_length=32)
    return f"shifter-range-{range_id}-raes-domain-{digest}-{safe_purpose}"


def _canonical_raes_directory_secret_id(
    range_id: int,
    domain_id: str,
    subject_address: str,
    purpose: str,
) -> str:
    """Return the canonical id for a range-local RAES directory credential."""
    identity = "\0".join((domain_id, subject_address)).encode("utf-8")
    credential_class = {
        "dsrm-password": DynamicSecretClass.RAES_DOMAIN_DSRM_PASSWORD,
        "authority-password": DynamicSecretClass.RAES_DOMAIN_AUTHORITY_PASSWORD,
        "account-password": DynamicSecretClass.RAES_DOMAIN_ACCOUNT_PASSWORD,
    }.get(purpose)
    if credential_class is None:
        raise ValueError(f"unsupported RAES directory secret purpose {purpose!r}")
    return canonical_secret_id(
        credential_class=credential_class,
        scope=f"range-{range_id}-domain-{hashlib.sha256(identity).hexdigest()[:40]}",
    )


def _password_length(strength: str) -> int:
    """Resolve an admitted password-strength label to its generated length."""
    length = _RAES_PASSWORD_LENGTHS.get(strength)
    if length is None:
        raise ValueError(f"unsupported password strength {strength!r}")
    return length


def ensure_raes_account_password_secret(
    range_id: int, instance_key: str, username: str, password_strength: str
) -> tuple[str, str]:
    """Create or read one authored account's password using explicit strength policy."""
    length = _password_length(password_strength)
    return _read_or_create_secret(
        _raes_account_secret_id(range_id, instance_key, username, "account-password"),
        lambda: generate_rdp_password(length),
        _canonical_raes_account_secret_id(range_id, instance_key, username, "account-password"),
    )


def ensure_raes_account_public_key_secret(range_id: int, instance_key: str, username: str) -> tuple[str, str]:
    """Create/read an authored account private key and return only its public half."""
    secret_name, private_key = _read_or_create_secret(
        _raes_account_secret_id(range_id, instance_key, username, "account-publickey"),
        lambda: generate_ssh_keypair()[0],
        _canonical_raes_account_secret_id(range_id, instance_key, username, "account-publickey"),
    )
    return secret_name, derive_ssh_public_key(private_key)


def ensure_raes_domain_dsrm_secret(range_id: int, domain_id: str) -> tuple[str, str]:
    """Create or read the distinct DSRM password for one range-local domain."""
    return _read_or_create_secret(
        _raes_directory_secret_id(range_id, domain_id, "dsrm", "dsrm-password"),
        lambda: generate_rdp_password(_password_length("strong")),
        _canonical_raes_directory_secret_id(range_id, domain_id, "dsrm", "dsrm-password"),
    )


def ensure_raes_domain_authority_secret(range_id: int, domain_id: str, password_strength: str) -> tuple[str, str]:
    """Create or read the built-in domain authority password."""
    return _read_or_create_secret(
        _raes_directory_secret_id(range_id, domain_id, "authority", "authority-password"),
        lambda: generate_rdp_password(_password_length(password_strength)),
        _canonical_raes_directory_secret_id(range_id, domain_id, "authority", "authority-password"),
    )


def ensure_raes_domain_account_password_secret(
    range_id: int,
    domain_id: str,
    account_address: str,
    password_strength: str,
) -> tuple[str, str]:
    """Create or read a domain-account password keyed by stable account address."""
    return _read_or_create_secret(
        _raes_directory_secret_id(range_id, domain_id, account_address, "account-password"),
        lambda: generate_rdp_password(_password_length(password_strength)),
        _canonical_raes_directory_secret_id(range_id, domain_id, account_address, "account-password"),
    )


def _delete_secret_locations(legacy_secret_id: str, canonical_id: str) -> None:
    """Delete exact legacy and canonical locations, ignoring absent resources."""
    try:
        client, google_exceptions, platform_project_id = _secret_client()
    except RuntimeError:
        return
    locations = secret_locations(
        platform_project_id=platform_project_id,
        dynamic_project_id=dynamic_secret_project_id(),
        legacy_secret_id=legacy_secret_id,
        canonical_secret_id=canonical_id,
    )
    delete_all(client, google_exceptions, locations)
    for secret_name in locations.delete_refs:
        logger.info("Deleted GCP dynamic secret location secret_fp=%s", safe_log_fingerprint(secret_name))


def _delete_raes_directory_secret(range_id: int, domain_id: str, subject_address: str, purpose: str) -> None:
    """Delete one deterministic directory secret when Secret Manager is configured."""
    _delete_secret_locations(
        _raes_directory_secret_id(range_id, domain_id, subject_address, purpose),
        _canonical_raes_directory_secret_id(range_id, domain_id, subject_address, purpose),
    )


def delete_raes_domain_dsrm_secret(range_id: int, domain_id: str) -> None:
    """Delete the DSRM secret for one range-local domain."""
    _delete_raes_directory_secret(range_id, domain_id, "dsrm", "dsrm-password")


def delete_raes_domain_authority_secret(range_id: int, domain_id: str) -> None:
    """Delete the RID-500 authority secret for one range-local domain."""
    _delete_raes_directory_secret(range_id, domain_id, "authority", "authority-password")


def delete_raes_domain_account_secret(range_id: int, domain_id: str, account_address: str) -> None:
    """Delete one domain-account password secret by stable account address."""
    _delete_raes_directory_secret(range_id, domain_id, account_address, "account-password")


def delete_raes_ssh_secret(range_id: int, instance_key: str) -> None:
    """Delete the provisioner-managed SSH secret for one RAES range instance."""
    _delete_secret_locations(
        _raes_secret_id(range_id, instance_key, "ssh"),
        canonical_secret_id(
            credential_class=DynamicSecretClass.RAES_HOST_SSH,
            scope=f"range-{range_id}-{instance_key}",
        ),
    )


def delete_raes_account_secret(range_id: int, instance_key: str, username: str, auth_method: str) -> None:
    """Delete one deterministic authored-account credential secret."""
    kind = _RAES_ACCOUNT_SECRET_KINDS.get(auth_method)
    if kind is None:
        raise ValueError(f"unsupported account auth method {auth_method!r}")
    _delete_secret_locations(
        _raes_account_secret_id(range_id, instance_key, username, kind),
        _canonical_raes_account_secret_id(range_id, instance_key, username, kind),
    )


def delete_guest_secret(range_id: int, instance: GuestInstance, kind: str) -> None:
    """Delete a per-instance guest secret, ignoring missing secrets."""
    _delete_secret_locations(
        _guest_secret_id(range_id, instance, kind),
        _canonical_guest_secret_id(range_id, instance, kind),
    )


def delete_ssh_secret(range_id: int, instance: GuestInstance) -> None:
    """Delete the per-instance SSH secret."""
    delete_guest_secret(range_id, instance, "ssh")


def delete_participant_ssh_secret(range_id: int, instance: GuestInstance) -> None:
    """Delete the per-instance participant SSH secret."""
    delete_guest_secret(range_id, instance, "participant-ssh")


def delete_rdp_password_secret(range_id: int, instance: GuestInstance) -> None:
    """Delete the per-instance password secret."""
    delete_guest_secret(range_id, instance, "rdp-password")
