"""CTF service-layer authorization helpers.

This module is the shared source of truth for cross-cutting ownership,
delegation, and platform-administration checks that organizer-content services
apply as defense-in-depth behind the view layer (issue #765, #1923, #1922).
Putting the policy here, rather than in a private helper inside
`ctf.services.challenge`, keeps services that don't own the policy (hint,
attachment, prerequisite, future organizer-scoped services) from depending on a
sibling service's private implementation detail.

Authority is resolved for a named operation and returns a closed, server-derived
source (ADR-052): the least authority that admits the actor, in the order owner,
delegated event-staff capability, then the platform-admin override. The override
is an active, non-temporary Django superuser and is orthogonal to CTF organizer
membership, `CTFEvent.created_by` ownership, and `CTFEventStaff` delegation; it
never changes or synthesizes those relationships and never authorizes event
creation.

The view/API layer resolves authority for fast, sanitized denials; the service
layer applies the owner/override gate again so any internal caller that bypasses
the view layer is still refused.
"""

from __future__ import annotations

import enum
import logging
from typing import TYPE_CHECKING

from ctf.exceptions import CTFPermissionError

if TYPE_CHECKING:
    from django.contrib.auth.base_user import AbstractBaseUser
    from django.contrib.auth.models import AnonymousUser

    from ctf.models import CTFEvent

    # Actor accepted by the authority predicate/resolver: a Django user, an
    # anonymous user, or None. Defensive ``getattr`` handles unauthenticated and
    # test-double inputs at runtime.
    Actor = AbstractBaseUser | AnonymousUser | None

logger = logging.getLogger(__name__)

# One delegable capability noun, several, or None (owner-only). Mirrors the API
# layer's ``Capability`` alias without importing across the layer boundary.
Capability = str | tuple[str, ...] | None


class EventAuthoritySource(enum.StrEnum):
    """Closed, server-derived source that admits an actor for an event operation.

    Never accepted from a request, cached as a user/event role, or supplied by a
    caller (ADR-052-R2). ``StrEnum`` so it serializes as its value in audit
    records and comparisons without an explicit ``.value``.
    """

    OWNER = "owner"
    EVENT_STAFF = "event_staff"
    PLATFORM_ADMIN = "platform_admin"


def is_ctf_platform_admin(user: Actor) -> bool:
    """Return whether ``user`` holds global CTF administration authority (ADR-052-R1).

    The sole global authority is an active, non-temporary Django superuser.
    ``is_staff``, Django model permissions, groups, provider claims, API-token
    scopes, organization/workspace roles, and client flags grant nothing. A
    marked temporary CTF account is deny-authoritative even if its flags or
    groups drift, so this predicate can never be satisfied by an event-scoped
    participant account that reaches ``/api/v1/ctf/`` through path admission.
    """
    from management.services import is_platform_operator

    return is_platform_operator(user)


def _staff_capability_matches(actor_pk: int, event: CTFEvent, capability: Capability) -> bool:
    """Return whether a live staff row for ``actor_pk`` grants any requested ``capability``."""
    from ctf.services.event.staff import staff_row_grants_capability

    if capability is None:
        return False
    wanted = (capability,) if isinstance(capability, str) else tuple(capability)
    return any(staff_row_grants_capability(actor_pk, event, item) for item in wanted)


def _capability_is_known(capability: Capability) -> bool:
    """Return whether every named capability belongs to the closed vocabulary (#1922).

    A ``None`` (owner-only) selector is always known. A named capability outside
    :class:`ctf.enums.EventCapability` is a typo or an operation missing from the
    role map; the resolver denies it for everyone — owner included — rather than
    silently authorizing.
    """
    if capability is None:
        return True
    from ctf.enums import EventCapability

    values = {cap.value for cap in EventCapability}
    wanted = (capability,) if isinstance(capability, str) else tuple(capability)
    return all(str(item) in values for item in wanted)


def resolve_event_authority(
    actor: Actor, event: CTFEvent, *, capability: Capability = None
) -> EventAuthoritySource | None:
    """Resolve the least-authority source admitting ``actor`` for an operation on ``event``.

    Order (ADR-052-R2): the event owner, then a live event-staff row whose role
    grants the requested ``capability`` (a full co-organizer holds every
    operational capability, #1922), then the platform-admin override.
    ``capability`` is ``None`` for the owner-only authority-topology operations
    (staff management, ownership transfer); a string or tuple of strings names a
    delegable capability. Returns ``None`` when the actor is not admitted; the
    caller renders one opaque denial.
    """
    actor_pk = getattr(actor, "pk", None)
    source: EventAuthoritySource | None = None
    if actor_pk is None or not _capability_is_known(capability):
        source = None
    elif event.created_by_id == actor_pk:
        source = EventAuthoritySource.OWNER
    elif _staff_capability_matches(actor_pk, event, capability):
        source = EventAuthoritySource.EVENT_STAFF
    elif is_ctf_platform_admin(actor):
        source = EventAuthoritySource.PLATFORM_ADMIN
    return source


def _actor_id_is_platform_admin(actor_id: int) -> bool:
    """Resolve ``actor_id`` to a user and apply :func:`is_ctf_platform_admin`.

    Used by the ``actor_id``-only service gate. Runs only on the non-owner path,
    so an owner mutation issues no extra query.
    """
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.filter(pk=actor_id).first()
    return is_ctf_platform_admin(user)


def assert_actor_owns_event(actor_id: int, event: CTFEvent) -> None:
    """Raise ``CTFPermissionError`` unless the actor owns the event or holds the override.

    Reserved for owner-only authority-topology operations. Most operational
    mutators use :func:`assert_event_capability` so full co-organizers are
    admitted too (#1922). Defense-in-depth service gate (issue #765): the event
    owner passes with no extra query; the platform-admin override (ADR-052)
    resolves the actor once on the non-owner path. This gate decides admission
    only. Callers that must distinguish and audit the ``platform_admin`` source
    resolve it explicitly at the request boundary via
    :func:`resolve_event_authority` (ADR-052-R4). The error envelope
    intentionally omits the owner pk to avoid leaking internal user identifiers;
    details name only the requested event.
    """
    if event.created_by_id == actor_id:
        return
    if _actor_id_is_platform_admin(actor_id):
        return
    logger.warning(
        "CTF service permission denied: actor=%s event=%s",
        actor_id,
        event.id,
    )
    raise CTFPermissionError(
        "Actor does not own this event",
        details={"event_id": str(event.id)},
    )


def assert_event_capability(actor_id: int, event: CTFEvent, capability: str) -> None:
    """Raise ``CTFPermissionError`` unless ``actor_id`` may exercise ``capability``.

    Defense-in-depth service gate (issue #765, #1922) for operational mutators
    (challenges, hints, attachments, prerequisites, content, config, lifecycle,
    ranges, delete, ...). Admits the owner, a live staff role the closed role map
    grants the capability to (a full co-organizer holds every operational
    capability), or the platform-admin override — the same least-authority order
    as :func:`resolve_event_authority`, which it delegates to. Fail closed:
    an unknown role/capability or an ineligible (deactivated / demoted) staff
    account is denied. The error envelope names only the event.
    """
    if event.created_by_id == actor_id:
        return
    from django.contrib.auth import get_user_model

    actor = get_user_model().objects.filter(pk=actor_id).first()
    if resolve_event_authority(actor, event, capability=capability) is not None:
        return
    logger.warning(
        "CTF service capability denied: actor=%s event=%s capability=%s",
        actor_id,
        event.id,
        capability,
    )
    raise CTFPermissionError(
        "Actor lacks the required event capability",
        details={"event_id": str(event.id)},
    )
