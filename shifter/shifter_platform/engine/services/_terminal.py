"""RDP / SSH terminal connection helpers."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from engine.secrets import SecretsError
from shared.enums import ResourceStatus

from ._common import (
    _first_connection_value,
    _resolve_instance_connection_name,
    _resolve_instance_host,
    _resolve_instance_ssh_key_secret_ref,
    _resolve_instance_ssh_username,
    _resolve_ngfw_management_ip,
    _resolve_ngfw_ssh_key_secret_ref,
    _resolve_rdp_credentials,
)


def _get_ssh_key(secret_ref: str) -> str:
    """Late-bound call to ``engine.secrets.get_ssh_key``.

    Importing the function inside the call (rather than at module top)
    lets tests patch ``engine.secrets.get_ssh_key`` and have the mock
    affect every submodule call site — the canonical patch-at-source
    pattern.
    """
    from engine.secrets import get_ssh_key

    return get_ssh_key(secret_ref)


if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from engine.ssh import SSHConnection

logger = logging.getLogger(__name__)

_USER_REQUIRED_MSG = "user is required"


def _require_rdp_password(instance: dict[str, Any], os_type: str, rdp_password: str | None) -> None:
    """Fail loud when a range guest has no RDP password.

    Minting a Guacamole RDP URL with an empty password would either fail
    silently or produce an unusable session; mission_control's RDP view
    maps ``ValueError`` -> HTTP 400 so the operator sees the specific
    reason rather than a silent broken connection.
    """
    if rdp_password:
        return

    role = _first_connection_value(instance.get("role"), "instance").lower()
    if os_type == "windows" and role == "dc":
        provider_label = _first_connection_value(instance.get("cloud_provider")).lower() or "aws"
        portal_provider = os.environ.get("CLOUD_PROVIDER", "aws").lower()
        if provider_label != portal_provider:
            raise ValueError(
                f"DC password unavailable: instance provider {provider_label!r} "
                f"does not match portal deployment provider {portal_provider!r}; "
                f"DC_DOMAIN_PASSWORD is scoped to the portal's own provider"
            )
        raise ValueError(
            "DC_DOMAIN_PASSWORD is not configured; seed the DC domain password secret and restart the portal"
        )

    raise ValueError(
        "RDP credentials are not available for this instance; the provisioner did not "
        "record a per-instance password secret reference"
    )


def _fetch_sftp_ssh_key(instance: dict[str, Any], os_type: str) -> str | None:
    """SSH key used for SFTP file transfers to a Windows instance.

    Windows uses key-based auth; Linux instances use password auth, so this
    returns ``None`` for them. A lookup failure is logged and swallowed —
    SFTP is best-effort and must not block the RDP session.
    """
    if os_type != "windows":
        return None
    ssh_key_ref = _resolve_instance_ssh_key_secret_ref(instance)
    if not ssh_key_ref:
        return None
    try:
        result = _get_ssh_key(ssh_key_ref)
    except SecretsError as e:
        logger.warning("Failed to get SSH key for SFTP: %s", e)
        result = None
    return result


def get_rdp_connection_info(user: User, instance_uuid: str) -> dict[str, Any]:
    """Get connection info for RDP access to a range instance."""
    from engine.models import Range

    if user is None:
        raise ValueError(_USER_REQUIRED_MSG)
    if not instance_uuid:
        raise ValueError("instance_uuid is required")

    logger.debug("get_rdp_connection_info: user=%s instance_uuid=%s", user.id, instance_uuid)

    range_obj = Range.get_active_for_user(user)
    if not range_obj:
        raise ValueError("No active range found")
    if range_obj.status != Range.Status.READY:
        raise ValueError(f"Range is not ready (status: {range_obj.status})")

    instance = range_obj.get_instance_by_uuid(instance_uuid)
    if not instance:
        raise ValueError(f"Instance {instance_uuid} not found in range")

    os_type = _first_connection_value(instance.get("os_type"), instance.get("os")).lower()
    if os_type not in ("kali", "ubuntu", "windows"):
        raise ValueError(f"RDP not available for {os_type} instances (no GUI)")

    host = _resolve_instance_host(instance)
    if not host:
        raise ValueError(f"Instance {instance_uuid} has no IP address")

    connection_name = _resolve_instance_connection_name(instance)
    rdp_username, rdp_password = _resolve_rdp_credentials(instance)
    _require_rdp_password(instance, os_type, rdp_password)

    return {
        "private_ip": host,
        "host": host,
        "os_type": os_type,
        "connection_name": connection_name,
        "rdp_username": rdp_username,
        "rdp_password": rdp_password,
        "ssh_key": _fetch_sftp_ssh_key(instance, os_type),
    }


def get_ssh_connection_info(user: User, instance_uuid: str) -> dict[str, Any]:
    """Get SSH connection details for a range instance."""
    from engine.models import Range

    if user is None:
        raise ValueError(_USER_REQUIRED_MSG)
    if not instance_uuid:
        raise ValueError("instance_uuid is required")

    logger.debug("connect_terminal: user_id=%s instance_uuid=%s", user.id, instance_uuid)

    range_obj = Range.objects.filter(
        provisioned_instances__contains=[{"uuid": instance_uuid}],
        user=user,
    ).first()

    if not range_obj:
        logger.error("Range not found for instance: user_id=%s instance_uuid=%s", user.id, instance_uuid)
        raise ValueError(f"No range found containing instance {instance_uuid}")

    if range_obj.status != Range.Status.READY:
        logger.error("Range not ready: range_id=%s status=%s", range_obj.id, range_obj.status)
        raise ValueError(f"Range is not ready (status: {range_obj.status})")

    instance = range_obj.get_instance_by_uuid(instance_uuid)
    if instance is None:
        logger.error("Instance not found: range_id=%s instance_uuid=%s", range_obj.id, instance_uuid)
        raise ValueError(f"Instance {instance_uuid} not found in range")

    ssh_key_ref = _resolve_instance_ssh_key_secret_ref(instance)
    if not ssh_key_ref:
        logger.error("No SSH key reference for instance: %s", instance_uuid)
        raise ValueError(f"Instance {instance_uuid} has no SSH key configured")

    ssh_key = _get_ssh_key(ssh_key_ref)

    host = _resolve_instance_host(instance)
    if not host:
        logger.error("No IP address for instance: %s", instance_uuid)
        raise ValueError(f"Instance {instance_uuid} has no IP address")

    os_type = _first_connection_value(instance.get("os_type"), instance.get("os")).lower()
    username = _resolve_instance_ssh_username(instance)

    return {
        "host": host,
        "port": 22,
        "username": username,
        "private_key": ssh_key,
        "connection_name": _resolve_instance_connection_name(instance),
        "os_type": os_type,
        "private_ip": host,
        "cloud_provider": _first_connection_value(instance.get("cloud_provider")).lower(),
    }


def connect_terminal(user: User, instance_uuid: str) -> SSHConnection:
    """Get SSH connection to instance."""
    from engine.ssh import SSHConnection

    ssh_info = get_ssh_connection_info(user, instance_uuid)
    # Windows doesn't have tmux, so skip session_id for Windows
    session_id = None if ssh_info["os_type"] == "windows" else instance_uuid

    return SSHConnection(
        host=ssh_info["host"],
        username=ssh_info["username"],
        private_key=ssh_info["private_key"],
        port=ssh_info["port"],
        session_id=session_id,
    )


def connect_ngfw_terminal(user: User, ngfw_uuid: str) -> SSHConnection:
    """Get SSH connection to NGFW management interface."""
    from engine.models import Instance
    from engine.ssh import SSHConnection

    if user is None:
        raise ValueError(_USER_REQUIRED_MSG)
    if not ngfw_uuid:
        raise ValueError("ngfw_uuid is required")

    logger.debug("connect_ngfw_terminal: user_id=%s ngfw_uuid=%s", user.id, ngfw_uuid)

    try:
        ngfw_instance = Instance.objects.select_related("request").get(
            uuid=ngfw_uuid,
            role=Instance.Role.NGFW,
        )
    except Instance.DoesNotExist:
        logger.error("NGFW instance not found: user_id=%s ngfw_uuid=%s", user.id, ngfw_uuid)
        raise ValueError(f"NGFW instance {ngfw_uuid} not found") from None

    if ngfw_instance.request is None:
        logger.error("NGFW instance has no associated request: ngfw_uuid=%s", ngfw_uuid)
        raise ValueError(f"NGFW instance {ngfw_uuid} has no associated request")

    if ngfw_instance.request.user != user:
        logger.error(
            "Permission denied: user_id=%s does not own ngfw_uuid=%s (owner=%s)",
            user.id,
            ngfw_uuid,
            ngfw_instance.request.user.id,
        )
        raise PermissionError(f"You do not have permission to access NGFW {ngfw_uuid}")

    if ngfw_instance.status != ResourceStatus.READY.value:
        logger.error(
            "NGFW not accessible: ngfw_uuid=%s status=%s (expected ready)",
            ngfw_uuid,
            ngfw_instance.status,
        )
        raise ValueError(f"NGFW is not accessible (status: {ngfw_instance.status}). NGFW must be in ready state.")

    if not ngfw_instance.state:
        logger.error("NGFW has no state: ngfw_uuid=%s", ngfw_uuid)
        raise ValueError(f"NGFW {ngfw_uuid} has no infrastructure state")

    management_ip = _resolve_ngfw_management_ip(ngfw_instance.state)
    if not management_ip:
        logger.error("No management IP in NGFW state: ngfw_uuid=%s", ngfw_uuid)
        raise ValueError(f"NGFW {ngfw_uuid} has no management IP configured")

    ssh_key_ref = _resolve_ngfw_ssh_key_secret_ref(ngfw_instance.state)
    if not ssh_key_ref:
        logger.error("No SSH key ARN in NGFW state: ngfw_uuid=%s", ngfw_uuid)
        raise ValueError(f"NGFW {ngfw_uuid} has no SSH key configured")

    ssh_key = _get_ssh_key(ssh_key_ref)

    logger.info(
        "Creating SSH connection for NGFW: user_id=%s ngfw_uuid=%s management_ip=%s",
        user.id,
        ngfw_uuid,
        management_ip,
    )

    return SSHConnection(
        host=management_ip,
        username="admin",
        private_key=ssh_key,
        port=22,
        # PAN-OS doesn't support tmux
        session_id=None,
    )
