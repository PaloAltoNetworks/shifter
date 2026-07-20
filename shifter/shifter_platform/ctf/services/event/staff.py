"""Delegated event-staff roles: moderators and judges (CTF-607).

The owning organizer (``CTFEvent.created_by``) always holds every capability;
staff rows grant other organizer-tier users a bounded slice of one event's
management surface. Capabilities are coarse nouns matched by the API layer:

- ``participants``: manage the participant roster and moderation actions
- ``notifications``: manage announcements and notifications
- ``awards``: grant and revoke awards
- ``submissions``: read submissions and score timelines

Event configuration, challenges, and scoring settings are never delegated.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.contrib.auth.models import User

from ctf.enums import EventStaffRole
from ctf.exceptions import CTFNotFoundError, CTFValidationError
from ctf.models import CTFEvent, CTFEventStaff
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from uuid import UUID

    from django.contrib.auth.models import AnonymousUser
    from django.db.models import QuerySet

logger = logging.getLogger(__name__)

_ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    EventStaffRole.MODERATOR.value: frozenset({"participants", "notifications"}),
    EventStaffRole.JUDGE.value: frozenset({"awards", "submissions"}),
}


def actor_has_event_capability(actor: User | AnonymousUser, event: CTFEvent, capability: str) -> bool:
    """Return whether `actor` may exercise `capability` on `event`.

    The owning organizer always may; otherwise a live staff row whose role
    grants the capability is required.
    """
    actor_pk = actor.pk
    if actor_pk is None:
        return False
    if event.created_by_id == actor_pk:
        return True
    role = (
        CTFEventStaff.objects.filter(event=event, user_id=actor_pk, deleted_at__isnull=True)
        .values_list("role", flat=True)
        .first()
    )
    return role is not None and capability in _ROLE_CAPABILITIES.get(role, frozenset())


def _resolve_owned_event_for_staff(event_id: UUID, actor: User | AnonymousUser) -> CTFEvent:
    """Load the event and require the owning organizer (staff management is not delegable)."""
    try:
        event = CTFEvent.objects.get(pk=event_id, deleted_at__isnull=True)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(f"Event {event_id} not found", details={"event_id": str(event_id)}) from None
    if event.created_by_id != actor.pk:
        raise CTFValidationError(
            "Only the event organizer may manage staff",
            code="CTF_PERMISSION_DENIED",
        )
    return event


def assign_event_staff(event_id: UUID, actor: User | AnonymousUser, email: str, role: str) -> CTFEventStaff:
    """Assign (or re-role) a staff member on an owned event.

    The target is resolved by email and must be an active organizer-tier
    platform user — the organizer API surface requires that platform role, so
    a standard user could never exercise the delegation. Assigning an
    existing staff member changes their role.
    """
    from ctf.bridges import get_user_role

    if role not in _ROLE_CAPABILITIES:
        raise CTFValidationError(
            "Invalid staff role",
            code="CTF_INVALID_STAFF_ROLE",
            details={"role": role, "valid": sorted(_ROLE_CAPABILITIES)},
        )
    event = _resolve_owned_event_for_staff(event_id, actor)
    target = User.objects.filter(email__iexact=email.strip(), is_active=True).first()
    if target is None:
        raise CTFNotFoundError("No active user with that email", details={"email": email.strip()})
    if target.pk == event.created_by_id:
        raise CTFValidationError(
            "The event organizer already holds every capability",
            code="CTF_STAFF_IS_ORGANIZER",
        )
    if not get_user_role(target).is_ctf_organizer:
        raise CTFValidationError(
            "Staff members need the CTF organizer platform role",
            code="CTF_STAFF_ROLE_REQUIRED",
        )
    staff = CTFEventStaff.objects.filter(event=event, user=target, deleted_at__isnull=True).first()
    created = staff is None
    if staff is None:
        staff = CTFEventStaff.objects.create(event=event, user=target, role=role)
    elif staff.role != role:
        staff.role = role
        staff.save(update_fields=["role", "updated_at"])
    logger.info(
        "%s staff %s on event %s as %s",
        "Assigned" if created else "Re-roled",
        target.pk,
        event.pk,
        role,
    )
    return staff


def revoke_event_staff(event_id: UUID, actor: User | AnonymousUser, user_id: int) -> bool:
    """Remove a staff assignment from an owned event."""
    event = _resolve_owned_event_for_staff(event_id, actor)
    staff = CTFEventStaff.objects.filter(event=event, user_id=user_id, deleted_at__isnull=True).first()
    if staff is None:
        raise CTFNotFoundError("Staff assignment not found", details={"user_id": str(user_id)})
    staff.delete(soft=True)
    logger.info("Revoked staff %s on event %s", safe_log_value(user_id), event.pk)
    return True


def list_event_staff(event_id: UUID) -> QuerySet[CTFEventStaff]:
    """List live staff assignments for an event."""
    return (
        CTFEventStaff.objects.filter(event_id=event_id, deleted_at__isnull=True)
        .select_related("user")
        .order_by("created_at")
    )
