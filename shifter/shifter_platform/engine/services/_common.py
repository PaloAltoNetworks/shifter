"""Shared helpers used by every engine.services submodule.

These helpers project the raw provisioner-state instance payloads
(`engine.models.Range.provisioned_instances` entries) into the
display/connection values that the public service functions need:
host/IP, secret references, connection name, OS-derived defaults.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from engine.secrets import SecretsError

logger = logging.getLogger(__name__)


def _get_rdp_password(secret_ref: str) -> str:
    """Late-bound call to ``engine.services.get_rdp_password``.

    Tests for the RDP password path patch ``engine.services.get_rdp_password``
    (the historical public surface from before the engine.services split),
    so we look the name up through the ``engine.services`` package at
    call time to honor those mocks.
    """
    from engine import services as _es

    return _es.get_rdp_password(secret_ref)


class EngineError(Exception):
    """Base exception for engine service errors."""


def _first_connection_value(*values: object) -> str:
    """Return the first non-empty connection value as a normalized string."""
    for value in values:
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                return normalized
        elif value not in (None, ""):
            return str(value)
    return ""


def _get_instance_provider_metadata(instance: dict[str, Any]) -> dict[str, Any]:
    """Return the provider-specific metadata block for an instance payload."""
    provider_metadata = instance.get("provider_metadata")
    if not isinstance(provider_metadata, dict):
        return {}

    # Probe order: caller-declared cloud_provider first (if any), then the
    # known providers in the historical fallback order.
    declared_provider = _first_connection_value(instance.get("cloud_provider")).lower()
    candidates = [declared_provider, "gcp", "gdc", "aws"] if declared_provider else ["gcp", "gdc", "aws"]
    for provider_name in candidates:
        metadata = provider_metadata.get(provider_name)
        if isinstance(metadata, dict):
            return metadata
    return {}


def _resolve_instance_host(instance: dict[str, Any]) -> str:
    """Resolve the best internal host/IP for guest connectivity."""
    provider_metadata = _get_instance_provider_metadata(instance)
    return _first_connection_value(
        instance.get("host"),
        instance.get("private_ip"),
        instance.get("privateIp"),
        instance.get("internal_ip"),
        instance.get("internalIp"),
        provider_metadata.get("private_ip"),
        provider_metadata.get("privateIp"),
        provider_metadata.get("network_ip"),
        provider_metadata.get("internal_ip"),
        provider_metadata.get("internalIp"),
        provider_metadata.get("guest_ip"),
        provider_metadata.get("vm_ip"),
        provider_metadata.get("ip"),
    )


def _resolve_instance_ssh_key_secret_ref(instance: dict[str, Any]) -> str:
    """Resolve the active secret reference for the instance SSH key."""
    provider_metadata = _get_instance_provider_metadata(instance)
    return _first_connection_value(
        instance.get("ssh_key_secret_arn"),
        instance.get("ssh_key_secret_id"),
        provider_metadata.get("ssh_key_secret_arn"),
        provider_metadata.get("ssh_key_secret_id"),
        provider_metadata.get("ssh_secret_ref"),
        provider_metadata.get("ssh_secret_id"),
    )


def _resolve_instance_rdp_password_secret_ref(instance: dict[str, Any]) -> str:
    """Resolve the active secret reference for the per-instance RDP password.

    Mirrors ``_resolve_instance_ssh_key_secret_ref`` so the per-instance
    credential reference can live either at the top of the instance
    payload (AWS engine state, parallel to ``ssh_key_secret_arn``) or
    nested under the provider-specific metadata block (GDC VM Runtime
    payloads under ``provider_metadata.gdc``).
    """
    provider_metadata = _get_instance_provider_metadata(instance)
    return _first_connection_value(
        instance.get("rdp_password_secret_arn"),
        instance.get("rdp_password_secret_id"),
        instance.get("rdp_password_secret_ref"),
        provider_metadata.get("rdp_password_secret_arn"),
        provider_metadata.get("rdp_password_secret_id"),
        provider_metadata.get("rdp_password_secret_ref"),
    )


def _resolve_instance_connection_name(instance: dict[str, Any]) -> str:
    """Resolve a stable display name for RDP/SSH Guacamole connections."""
    provider_metadata = _get_instance_provider_metadata(instance)
    resolved_name = _first_connection_value(
        instance.get("name"),
        provider_metadata.get("instance_name"),
        provider_metadata.get("vm_name"),
        provider_metadata.get("name"),
    )
    if resolved_name:
        return resolved_name

    os_type = _first_connection_value(instance.get("os_type"), instance.get("os")).lower()
    role = _first_connection_value(instance.get("role"), "instance").lower()
    display_role = "target" if role == "victim" else role
    return f"{display_role}-{os_type or 'instance'}"


_OS_DEFAULT_SSH_USERNAMES = {
    "kali": "kali",
    "amazon-linux": "ec2-user",
    "windows": "Administrator",
}


def _resolve_instance_ssh_username(instance: dict[str, Any]) -> str:
    """Resolve the guest SSH username for terminal and Guacamole access."""
    provider_metadata = _get_instance_provider_metadata(instance)
    explicit_username = _first_connection_value(
        instance.get("ssh_username"),
        instance.get("ssh_user"),
        provider_metadata.get("ssh_username"),
        provider_metadata.get("ssh_user"),
        provider_metadata.get("username"),
    )
    if explicit_username:
        return explicit_username

    os_type = _first_connection_value(instance.get("os_type"), instance.get("os")).lower()
    return _OS_DEFAULT_SSH_USERNAMES.get(os_type, "ubuntu")


def _resolve_dc_password(instance: dict[str, Any]) -> str | None:
    """Return the DC Administrator password for a Windows DC instance.

    ``DC_DOMAIN_PASSWORD`` is the env-var contract shared with the engine
    provisioner (``shifter/engine/provisioner/main.py`` for AWS,
    ``shifter/engine/provisioner/gdc_vmruntime_assets.py`` for GCP), so
    the portal reads the same env-var. The credential is deployment-scoped:
    the portal's own ``CLOUD_PROVIDER`` env identifies which provider's DC
    password lives in ``DC_DOMAIN_PASSWORD``. Returning that value for an
    instance from a different provider would leak the portal-deployment
    provider's credential to the requesting provider's user — refuse with
    ``None`` instead.

    An empty ``cloud_provider`` (older payloads) is treated as ``"aws"``,
    matching the default elsewhere in the engine state handling.

    Per ADR-004-R7 and the architecture preflight for #762, treating the
    DC domain Administrator credential as the local desktop RDP credential
    is intentional only for the DC host itself; non-DC guests use
    per-instance secret references.
    """
    instance_provider = _first_connection_value(instance.get("cloud_provider")).lower() or "aws"
    portal_provider = os.environ.get("CLOUD_PROVIDER", "aws").lower()
    if instance_provider != portal_provider:
        return None
    return os.environ.get("DC_DOMAIN_PASSWORD")


def _resolve_non_dc_rdp_password(instance: dict[str, Any]) -> str | None:
    """Resolve a non-DC guest RDP password from the per-instance secret store.

    Returns ``None`` when no secret reference is recorded for the
    instance. ``get_rdp_connection_info`` converts ``None`` into an
    explicit ``ValueError`` so the portal fails closed instead of
    minting a Guacamole RDP URL with a missing or empty password.

    Provider fetch failures (deleted secret version, IAM regression,
    transient cloud error) raise ``ValueError`` rather than letting a
    ``SecretsError`` escape: the mission_control RDP view's error
    envelope only converts ``ValueError`` into a non-sensitive 400, so
    re-raising here keeps the user-facing failure shape identical to
    "no reference recorded" instead of bubbling up as an unhandled 500.
    The operational details (secret reference, provider error chain)
    stay in the warning log, never in the response.
    """
    secret_ref = _resolve_instance_rdp_password_secret_ref(instance)
    if not secret_ref:
        return None
    try:
        return _get_rdp_password(secret_ref)
    except SecretsError:
        logger.warning(
            "Failed to fetch per-instance RDP password (instance_uuid=%s); treating as credentials-unavailable",
            instance.get("uuid"),
            exc_info=True,
        )
        raise ValueError(
            "RDP credentials are not available for this instance; the credential store "
            "did not return a value for the recorded secret reference"
        ) from None


_OS_DEFAULT_RDP_USERNAMES = {
    "windows": "Administrator",
    "kali": "kali",
    "ubuntu": "ubuntu",
}


def _resolve_rdp_credentials(instance: dict[str, Any]) -> tuple[str | None, str | None]:
    """Resolve the RDP username/password pair for a provisioned guest.

    Per-instance credentials (per #762): non-DC guests use a per-instance
    secret reference resolved through the active provider secret store.
    No shared literal fallbacks. The DC role keeps the deployment-scoped
    ``DC_DOMAIN_PASSWORD`` lookup (separate concern — domain admin).
    """
    os_type = _first_connection_value(instance.get("os_type"), instance.get("os")).lower()
    username = _OS_DEFAULT_RDP_USERNAMES.get(os_type)
    if username is None:
        return None, None
    role = _first_connection_value(instance.get("role"), "instance").lower()
    if os_type == "windows" and role == "dc":
        return username, _resolve_dc_password(instance)
    return username, _resolve_non_dc_rdp_password(instance)


def _get_ngfw_provider_metadata(state: dict[str, Any]) -> dict[str, Any]:
    """Return the provider-specific metadata block for an NGFW state payload."""
    provider_metadata = state.get("provider_metadata")
    if not isinstance(provider_metadata, dict):
        return {}

    declared_provider = _first_connection_value(state.get("cloud_provider")).lower()
    candidates = [declared_provider, "gcp", "gdc", "aws"] if declared_provider else ["gcp", "gdc", "aws"]
    for provider_name in candidates:
        metadata = provider_metadata.get(provider_name)
        if isinstance(metadata, dict):
            return metadata
    return {}


def _resolve_ngfw_management_ip(state: dict[str, Any]) -> str:
    """Resolve the best management IP for an NGFW state payload."""
    provider_metadata = _get_ngfw_provider_metadata(state)
    return _first_connection_value(
        state.get("management_ip"),
        provider_metadata.get("management_ip"),
    )


def _resolve_ngfw_ssh_key_secret_ref(state: dict[str, Any]) -> str:
    """Resolve the SSH key secret reference for NGFW terminal access."""
    provider_metadata = _get_ngfw_provider_metadata(state)
    return _first_connection_value(
        state.get("ssh_key_secret_arn"),
        state.get("ssh_key_secret_id"),
        provider_metadata.get("ssh_key_secret_arn"),
        provider_metadata.get("ssh_key_secret_id"),
        provider_metadata.get("ssh_secret_ref"),
        provider_metadata.get("ssh_secret_id"),
    )
