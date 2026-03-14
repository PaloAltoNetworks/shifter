"""Bridge module for cross-domain integrations.

All external service calls from the CTF app go through this module.
This isolates domain boundaries -- if external APIs change, only
this file needs updating.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UserRole:
    """CTF role information for a user."""

    is_ctf_organizer: bool
    is_ctf_participant: bool
    active_ctf_event: Any  # CTFEvent | None


def get_user_role(user: User) -> UserRole:
    """Get CTF role info for a user via Django Groups."""
    from management.services import get_user_profile
    from shared.auth import CTF_ORGANIZER_GROUP, CTF_PARTICIPANT_GROUP

    is_organizer = user.groups.filter(name=CTF_ORGANIZER_GROUP).exists()
    is_participant = user.groups.filter(name=CTF_PARTICIPANT_GROUP).exists()

    profile = get_user_profile(user)
    active_event = profile.active_ctf_event if is_participant else None

    return UserRole(
        is_ctf_organizer=is_organizer,
        is_ctf_participant=is_participant,
        active_ctf_event=active_event,
    )


@dataclass(frozen=True)
class RangeProvisionResult:
    """Result of a range provisioning request."""

    request_id: Any  # UUID


def cms_create_range(user, scenario, agents_by_os, ngfw_enabled) -> RangeProvisionResult:
    """Create a range via CMS."""
    import cms.services as cms_services

    result = cms_services.create_range(
        user=user,
        scenario=scenario,
        agents_by_os=agents_by_os,
        ngfw_enabled=ngfw_enabled,
    )
    return RangeProvisionResult(request_id=result.request_id)


def cms_destroy_range(user, range_instance_id: int) -> None:
    """Destroy a range via CMS."""
    import cms.services as cms_services

    cms_services.destroy_range(user, range_instance_id)


def cms_find_range_instance_id(request_id) -> int | None:
    """Find RangeInstance PK by provisioning request ID."""
    from cms.models import RangeInstance

    instance = RangeInstance.objects.filter(request__request_id=request_id).first()
    return instance.pk if instance else None


def cms_get_range_status(range_instance_id: int) -> str:
    """Get fresh range status from CMS."""
    from cms.models import RangeInstance

    try:
        return RangeInstance.objects.get(pk=range_instance_id).status
    except RangeInstance.DoesNotExist:
        return "unknown"


def cms_get_range_spec(range_instance_id: int) -> dict | None:
    """Get range_spec dict from CMS RangeInstance."""
    from cms.models import RangeInstance

    try:
        return RangeInstance.objects.get(pk=range_instance_id).range_spec
    except RangeInstance.DoesNotExist:
        return None


def cms_list_scenarios(user: User) -> list[tuple[str, str]]:
    """List available scenarios as (id, name) tuples for form choices.

    Args:
        user: Requesting user (used for access filtering).

    Returns:
        List of (scenario_id, name) tuples sorted by name.
    """
    from cms.scenarios.registry import list_all_scenarios

    scenarios = list_all_scenarios(user)
    return [(s["id"], s["name"]) for s in scenarios]


def get_range_connection_info(
    user: User,
    range_instance_id: int,
    instance_uuid: str | None = None,
) -> dict[str, Any]:
    """Get full connection info for a CTF range, including credentials.

    Bridges CMS RangeInstance -> Engine Range -> provisioned_instances to
    extract RDP credentials, SSH keys, and SFTP config — the same data
    that mission_control uses for Guacamole access.

    Args:
        user: The participant user.
        range_instance_id: CMS RangeInstance PK.
        instance_uuid: Optional UUID of a specific provisioned instance.
            If None, selects the first GUI-capable instance
            (kali > windows > ubuntu).

    Returns:
        Dict with: private_ip, os_type, connection_name, rdp_username,
        rdp_password, ssh_key, sftp_root_directory.
    """
    from cms.models import RangeInstance
    from engine.models import Range

    try:
        ri = RangeInstance.objects.get(pk=range_instance_id)
    except RangeInstance.DoesNotExist:
        raise ValueError(f"RangeInstance {range_instance_id} not found") from None

    # Find the Engine Range linked to this RangeInstance
    if ri.range_id is None:
        raise ValueError(f"RangeInstance {range_instance_id} has no range_id")
    try:
        engine_range = Range.objects.get(pk=ri.range_id)
    except Range.DoesNotExist:
        raise ValueError(f"Engine Range {ri.range_id} not found") from None

    instances: dict[str, Any] = engine_range.provisioned_instances or {}

    if not instances:
        raise ValueError("No provisioned instances available")

    # Select target instance
    target: dict[str, Any] | None = None
    if instance_uuid:
        target = instances.get(instance_uuid)
    else:
        # Prefer kali > windows > ubuntu for GUI access
        preference = ["kali", "windows", "ubuntu"]
        for pref in preference:
            for _uuid, inst in instances.items():
                os_type = (inst.get("os_type") or inst.get("os", "")).lower()
                name = (inst.get("name") or "").lower()
                if pref in os_type or pref in name:
                    target = inst
                    break
            if target:
                break
        # Fallback to first instance
        if target is None:
            target = next(iter(instances.values()))

    assert target is not None  # guaranteed by non-empty instances dict

    os_type = (target.get("os_type") or target.get("os", "")).lower()
    private_ip = target.get("private_ip", "")

    # Credential mapping (matches engine/services.py get_rdp_connection_info)
    if "windows" in os_type:
        rdp_username = "Administrator"
        role = (target.get("role") or "").lower()
        rdp_password = "Sh1fterDC2026" if role == "dc" else "CortexSavesTheDay!"  # nosec B105 — default VM credentials, same as engine/services.py
        sftp_root_directory = "/C:/Users/Administrator/Downloads"
        # Attempt to retrieve SSH key for Windows SFTP
        ssh_key = _get_instance_ssh_key(target)
    elif "kali" in os_type:
        rdp_username = "kali"
        rdp_password = "kali"  # nosec B105 — default VM credentials
        sftp_root_directory = "/home/kali"
        ssh_key = None
    else:
        # Ubuntu and other Linux
        rdp_username = "ubuntu"
        rdp_password = "ubuntu"  # nosec B105 — default VM credentials
        sftp_root_directory = "/home/ubuntu"
        ssh_key = None

    return {
        "private_ip": private_ip,
        "os_type": os_type,
        "connection_name": f"ctf-{range_instance_id}",
        "rdp_username": rdp_username,
        "rdp_password": rdp_password,
        "ssh_key": ssh_key,
        "sftp_root_directory": sftp_root_directory,
    }


def _get_instance_ssh_key(instance_data: dict) -> str | None:
    """Retrieve SSH key from Secrets Manager for a provisioned instance."""
    secret_arn = instance_data.get("ssh_key_secret_arn")
    if not secret_arn:
        return None
    try:
        import boto3
        from django.conf import settings

        client = boto3.client("secretsmanager", region_name=settings.AWS_REGION)
        response = client.get_secret_value(SecretId=secret_arn)
        return response.get("SecretString")
    except Exception:
        logger.warning("Failed to retrieve SSH key from %s", secret_arn)
        return None


def get_guacamole_rdp_url(
    username: str,
    connection_name: str,
    hostname: str,
    rdp_username: str | None = None,
    rdp_password: str | None = None,
    sftp_root_directory: str | None = None,
    sftp_private_key: str | None = None,
) -> str:
    """Generate Guacamole RDP access URL."""
    from django.conf import settings

    from mission_control.guacamole import create_guacamole_rdp_url

    return create_guacamole_rdp_url(
        base_url=settings.GUACAMOLE_BASE_URL,
        secret_key=settings.GUACAMOLE_JSON_AUTH_SECRET,
        username=username,
        connection_name=connection_name,
        hostname=hostname,
        api_base_url=settings.GUACAMOLE_API_BASE_URL,
        rdp_username=rdp_username,
        rdp_password=rdp_password,
        sftp_root_directory=sftp_root_directory,
        sftp_private_key=sftp_private_key,
    )
