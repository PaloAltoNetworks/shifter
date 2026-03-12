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
    """Get CTF role info for a user via management profile."""
    from management.services import get_user_profile

    profile = get_user_profile(user)
    return UserRole(
        is_ctf_organizer=profile.is_ctf_organizer,
        is_ctf_participant=profile.is_ctf_participant,
        active_ctf_event=profile.active_ctf_event if profile.is_ctf_participant else None,
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


def get_guacamole_rdp_url(username: str, connection_name: str, hostname: str) -> str:
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
    )
