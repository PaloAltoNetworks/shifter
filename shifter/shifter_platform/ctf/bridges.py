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

    active_event = None
    if is_participant:
        profile = get_user_profile(user)
        event_id = profile.active_ctf_event_id
        if event_id:
            from ctf.models import CTFEvent

            active_event = CTFEvent.objects.filter(pk=event_id).first()

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
    import cms.services as cms_services

    return cms_services.find_range_instance_id_by_request(request_id)


def cms_get_range_status(range_instance_id: int) -> str:
    """Get fresh range status from CMS."""
    import cms.services as cms_services

    return cms_services.get_range_status_by_id(range_instance_id)


def cms_get_range_spec(range_instance_id: int) -> dict | None:
    """Get range_spec dict from CMS RangeInstance."""
    import cms.services as cms_services

    return cms_services.get_range_spec_by_id(range_instance_id)


def cms_list_scenarios(user: User) -> list[tuple[str, str]]:
    """List available scenarios as (id, name) tuples for form choices.

    Args:
        user: Requesting user (used for access filtering).

    Returns:
        List of (scenario_id, name) tuples sorted by name.
    """
    import cms.services as cms_services

    scenarios = cms_services.list_scenarios(user)
    return [(s["id"], s["name"]) for s in scenarios]
