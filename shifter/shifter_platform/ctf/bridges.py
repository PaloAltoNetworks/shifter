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
    from datetime import datetime
    from uuid import UUID

    from django.contrib.auth.models import User

    from shared.remote_access import OpenVpnProfile

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
    from shared.auth import CTF_ORGANIZER_GROUP, CTF_PARTICIPANT_GROUP, get_user_group_names

    group_names = get_user_group_names(user)
    is_organizer = CTF_ORGANIZER_GROUP in group_names
    is_participant = CTF_PARTICIPANT_GROUP in group_names

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


def cms_declare_event_capacity(
    *,
    event_ref: UUID,
    event_name: str,
    expected_concurrent_ranges: int,
    cohort_size: int,
    window_start: datetime | None,
    window_end: datetime | None,
    resource_hints: dict[str, Any],
) -> None:
    """Declare event capacity to the provisioning engine (CTF-908).

    Best-effort producer contract: the declaration is recorded before spinup
    so capacity-aware provisioning works from declared intent (#621); range
    provisioning itself never depends on this call succeeding.
    """
    import cms.services as cms_services

    signal = cms_services.EngineEventCapacitySignal(
        event_ref=event_ref,
        event_name=event_name,
        expected_concurrent_ranges=expected_concurrent_ranges,
        cohort_size=cohort_size,
        window_start=window_start,
        window_end=window_end,
        resource_hints=resource_hints,
    )
    cms_services.engine_record_capacity_declaration(signal)


def cms_create_range(
    user: User,
    scenario: str,
    agents_by_os: dict[str, int],
    ngfw_enabled: bool,
    remote_access_teardown_at: datetime | None,
) -> RangeProvisionResult:
    """Create a CTF range via CMS.

    Passes range_source=RangeSource.CTF so the CMS admission check is scoped
    to CTF ranges, allowing the user to hold both a Mission Control range and a
    CTF range simultaneously (#450). The source is server-derived here and is
    never caller-supplied.
    """
    import cms.services as cms_services
    from shared.enums import RangeSource

    result = cms_services.create_range_dispatch(
        user=user,
        scenario=scenario,
        agents_by_os=agents_by_os,
        ngfw_enabled=ngfw_enabled,
        range_source=RangeSource.CTF,
        remote_access_teardown_at=remote_access_teardown_at,
    )
    return RangeProvisionResult(request_id=result.request_id)


def cms_destroy_range(user, range_instance_id: int) -> None:
    """Destroy a range via CMS."""
    import cms.services as cms_services

    cms_services.destroy_range(user, range_instance_id)


def cms_stop_range(user, range_instance_id: int) -> None:
    """Stop (pause) a range via CMS."""
    import cms.services as cms_services

    cms_services.pause_range(user, range_instance_id)


def cms_start_range(user, range_instance_id: int) -> None:
    """Start (resume) a range via CMS."""
    import cms.services as cms_services

    cms_services.resume_range(user, range_instance_id)


def cms_find_range_instance_id(request_id) -> int | None:
    """Find RangeInstance PK by provisioning request ID."""
    import cms.services as cms_services

    return cms_services.find_range_instance_id_by_request(request_id)


def cms_get_range_status(range_instance_id: int) -> str:
    """Get fresh range status from CMS."""
    import cms.services as cms_services

    return cms_services.get_range_status_by_id(range_instance_id)


def cms_get_range_target_instances(user: User) -> list[dict[str, str]]:
    """Return the participant-safe target-box projection for a user's ready range.

    Wraps ``cms.services.get_range_target_instances`` and projects each instance
    down to the participant-safe field allowlist (``uuid``, ``name``,
    ``private_ip``, ``os_type``). The projection is enforced here at the CTF/CMS
    boundary — not in a DRF serializer, which documents but does not filter a
    runtime ``Response`` dict — so range-internal metadata (roles, provider
    details, channel bindings, secret references) never crosses into the CTF
    participant surface (#1740). ``uuid`` is the identifier the Guacamole flow
    needs; the CMS range PK (``range_instance_id``) must never be sent instead.
    """
    import cms.services as cms_services

    return [
        {
            "uuid": str(instance.get("uuid") or ""),
            "name": str(instance.get("name") or ""),
            "private_ip": str(instance.get("private_ip") or ""),
            "os_type": str(instance.get("os_type") or ""),
        }
        for instance in cms_services.get_range_target_instances(user.pk)
    ]


def cms_get_range_spec(range_instance_id: int) -> dict | None:
    """Get range_spec dict from CMS RangeInstance."""
    import cms.services as cms_services

    return cms_services.get_range_spec_by_id(range_instance_id)


def cms_get_openvpn_profile(user: User, range_instance_id: int) -> OpenVpnProfile:
    """Resolve a participant profile through the public CMS service boundary."""
    import cms.services as cms_services
    from ctf.exceptions import CTFNotFoundError, CTFRangeError, CTFStateError

    try:
        return cms_services.get_ctf_openvpn_profile(user, range_instance_id)
    except cms_services.CtfOpenVpnProfileNotFound as exc:
        raise CTFNotFoundError("VPN profile is not available") from exc
    except cms_services.CtfOpenVpnProfileConflict as exc:
        raise CTFStateError("VPN profile is not ready") from exc
    except cms_services.CtfOpenVpnProfileUnavailable as exc:
        raise CTFRangeError("VPN profile is unavailable") from exc


def cms_has_openvpn_profile(user: User, range_instance_id: int) -> bool:
    """Project only safe OpenVPN readiness through CMS."""
    import cms.services as cms_services

    return cms_services.has_ctf_openvpn_profile(user, range_instance_id)


def cms_reconcile_ctf_range_leases(range_instance_ids: list[int], enforced_deadline: datetime) -> int:
    """Reconcile event-derived cleanup leases through the CMS boundary."""
    import cms.services as cms_services
    from ctf.exceptions import CTFValidationError

    try:
        return cms_services.reconcile_ctf_range_leases(range_instance_ids, enforced_deadline)
    except cms_services.RangeLeaseConflict as exc:
        raise CTFValidationError(
            "The requested cleanup time exceeds an existing range generation lifetime",
            code="CTF_RANGE_LEASE_CEILING",
        ) from exc


def cms_reassign_range_owner(range_instance_id: int, new_user: User) -> None:
    """Reassign an existing range's ownership via CMS (#1018 spare recovery)."""
    import cms.services as cms_services

    cms_services.reassign_range_owner(range_instance_id, new_user)


def cms_range_owner_reassignment_available(range_instance_id: int) -> bool:
    """Check spare-transfer safety through the public CMS boundary."""
    import cms.services as cms_services

    return cms_services.range_owner_reassignment_available(range_instance_id)


def cms_list_scenarios(user: User) -> list[tuple[str, str]]:
    """List CTF-event-selectable scenarios as (id, name) tuples for form choices.

    CTF event creation is a launch workflow, so this returns only scenarios that
    are launchable for the ``ctf_event`` workflow (legacy YAML/DB scenarios plus
    any launchable ACES package entries); non-launchable ACES review entries are
    excluded. Staff review of non-launchable entries lives in the CMS scenario
    editor, not in CTF event selection.

    Args:
        user: Requesting user (used for access filtering).

    Returns:
        List of (scenario_id, name) tuples sorted by name.
    """
    import cms.services as cms_services

    scenarios = cms_services.list_launchable_scenarios(user, "ctf_event")
    return [(s["id"], s["name"]) for s in scenarios]
