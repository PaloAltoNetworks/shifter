"""Participant query and eligibility helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from django.db.models import Q, QuerySet

from ctf.enums import ParticipantStatus
from ctf.exceptions import CTFNotFoundError
from ctf.models import CTFEvent, CTFParticipant

if TYPE_CHECKING:
    from django.contrib.auth.models import User

# Participant statuses considered "playing" for access-control AND scoring.
# DISQUALIFIED is intentionally excluded — a disqualified participant must
# be invisible to scoring AND blocked from access-control surfaces. Codex
# review #765/#768/#769 caught the predicate divergence between scoring
# and access checks; `eligible_participant_q` below is now the single
# source of truth and is reused by both layers.
_PLAYING_PARTICIPANT_STATUSES: tuple[str, ...] = (
    ParticipantStatus.ACTIVE.value,
    ParticipantStatus.REGISTERED.value,
    ParticipantStatus.COMPLETED.value,
)

# Statuses allowed on read-only event surfaces. CTF-609: a disqualified
# participant keeps VIEW access (challenges, scoreboard, own profile) while
# staying out of scoring and blocked from every mutation. BANNED (CTF-605)
# appears in neither tuple — a banned participant has no event access at all.
_VIEWING_PARTICIPANT_STATUSES: tuple[str, ...] = (
    *_PLAYING_PARTICIPANT_STATUSES,
    ParticipantStatus.DISQUALIFIED.value,
)


def eligible_participant_q(field_prefix: str = "") -> Q:
    """Return a `Q` predicate matching participants eligible for scoring/access.

    A participant is eligible iff they have completed registration
    (`registered_at` is set) AND their status is one of ACTIVE / REGISTERED
    / COMPLETED — i.e. NOT disqualified. This is the single shared
    predicate used by `is_active_participant` (access control), by
    `get_scoreboard` (individual rankings), and by `get_team_scoreboard`
    (team aggregates) so the three layers cannot drift apart.

    Args:
        field_prefix: Django ORM lookup prefix to prepend, e.g. `""` when
            filtering on `CTFParticipant` directly, or `"members__"` when
            filtering on `CTFTeam` and reaching across the team→members
            relation. Must end in `__` when non-empty.

    Returns:
        A `Q` object combining the registration and status checks.
    """
    p = field_prefix
    return Q(**{f"{p}registered_at__isnull": False, f"{p}status__in": _PLAYING_PARTICIPANT_STATUSES})


def viewing_participant_q(field_prefix: str = "") -> Q:
    """Return a `Q` predicate matching participants allowed to VIEW event content.

    Superset of :func:`eligible_participant_q`: identical registration check,
    but DISQUALIFIED rows are admitted (CTF-609 keeps their read access).
    Use this ONLY on read surfaces; every mutation and every scoring query
    must keep resolving through the compete predicate so a disqualified or
    banned row can never act or rank. The two predicates live side by side
    here so they cannot drift apart (the divergence class from reviews
    #765/#768/#769).

    Args:
        field_prefix: Same ORM prefix contract as :func:`eligible_participant_q`.

    Returns:
        A `Q` object combining the registration and view-status checks.
    """
    p = field_prefix
    return Q(**{f"{p}registered_at__isnull": False, f"{p}status__in": _VIEWING_PARTICIPANT_STATUSES})


def ranked_participant_q(field_prefix: str = "") -> Q:
    """Return a `Q` predicate matching participants who appear in rankings.

    Subset of :func:`eligible_participant_q`: hidden participants (CTF-606)
    and observers (CTF-604) play or watch without ever ranking, so every
    scoreboard read and materialized team-score rebuild must filter through
    this predicate. Individual materialized columns (``cached_score``) are
    still maintained for hidden participants — they see their own score.

    Args:
        field_prefix: Same ORM prefix contract as :func:`eligible_participant_q`.

    Returns:
        A `Q` object combining eligibility with the ranked-visibility checks.
    """
    from ctf.enums import ParticipantRole

    p = field_prefix
    return eligible_participant_q(field_prefix) & Q(**{f"{p}hidden": False, f"{p}role": ParticipantRole.PLAYER.value})


def assert_participant_can_compete(participant: CTFParticipant) -> None:
    """Raise unless `participant` may take competitive actions (submit, hints).

    The imperative twin of :func:`eligible_participant_q` for callers already
    holding a row, plus the CTF-604 role rule: observers watch but never act.
    Shared by flag submission and hint purchase so a mutation path can never
    be more permissive than the scoring predicate.

    Raises:
        CTFStateError: If the participant is unregistered or their status is
            outside the playing set (invited, disqualified, banned).
        CTFPermissionError: If the participant is an observer.
    """
    from ctf.enums import ParticipantRole
    from ctf.exceptions import CTFPermissionError, CTFStateError

    if participant.registered_at is None or participant.status not in _PLAYING_PARTICIPANT_STATUSES:
        raise CTFStateError(
            "Participant is not eligible",
            details={"participant_id": str(participant.id), "status": participant.status},
        )
    if participant.role == ParticipantRole.OBSERVER.value:
        raise CTFPermissionError(
            "Observers cannot submit flags or unlock hints",
            details={"participant_id": str(participant.id)},
        )


def is_active_participant(user: User, event: CTFEvent | None = None) -> bool:
    """Return True if `user` is a non-disqualified registered participant.

    Used by `@ctf_participant_required`, the scoreboard endpoint, the
    challenge-file download endpoint, and any other surface that needs the
    same predicate as the scoring service. Without this, a disqualified
    participant whose `registered_at` is still set could pass the gate even
    though scoring excludes their rows.

    Args:
        user: The Django user to check.
        event: When supplied, scope the check to a single event; otherwise
            "is participant of any event" (e.g. for the platform-wide
            participant role decorator).
    """
    qs = CTFParticipant.objects.filter(eligible_participant_q(), user=user)
    if event is not None:
        qs = qs.filter(event=event)
    return qs.exists()


def is_viewing_participant(user: User, event: CTFEvent | None = None) -> bool:
    """Return True if `user` may view event content (playing OR disqualified).

    The read-surface twin of :func:`is_active_participant` (CTF-609). Used by
    the canonical participant API's permission gate so a disqualified
    participant can still browse the event; mutations stay compete-gated in
    the service layer.
    """
    qs = CTFParticipant.objects.filter(viewing_participant_q(), user=user)
    if event is not None:
        qs = qs.filter(event=event)
    return qs.exists()


def get_viewing_participant_by_user(user: User, event_id: UUID | None = None) -> CTFParticipant | None:
    """Get a participant row for read surfaces (admits DISQUALIFIED, CTF-609).

    Same resolution contract as :func:`get_participant_by_user` (pass
    ``event_id`` on event-scoped routes) with the view predicate. Mutation
    paths MUST keep using :func:`get_participant_by_user`.
    """
    qs = CTFParticipant.objects.filter(viewing_participant_q(), user=user)
    if event_id:
        qs = qs.filter(event_id=event_id)
    return qs.select_related("event", "team").first()


def get_participant_by_user(user: User, event_id: UUID | None = None) -> CTFParticipant | None:
    """Get an eligible participant record for a user.

    Codex review (issue #765/#768/#769) cycle 4: this helper is the entry
    point for every challenge-, hint-, scoreboard-, and dashboard-scoped
    view that resolves "the participant for this request." It now filters
    by `eligible_participant_q()` so a user with mixed eligibility across
    events can never act as a disqualified row in event A just because
    they are also eligible in event B. Callers MUST pass `event_id` when
    the route names a specific event (or a challenge belonging to one),
    so a multi-event user resolves to the correct participant.

    Args:
        user: The Django user.
        event_id: Event UUID to filter by. Strongly recommended for
            challenge- or event-scoped surfaces; without it, the helper
            returns the first eligible row across any event, which is
            only the right semantic for surfaces that are platform-wide
            (the active-event dashboard pulls its event from
            `UserProfile.active_ctf_event_id` and passes it here).

    Returns:
        The CTFParticipant instance or None.
    """
    qs = CTFParticipant.objects.filter(eligible_participant_q(), user=user)
    if event_id:
        qs = qs.filter(event_id=event_id)

    return qs.select_related("event", "team").first()


def list_participants_for_event(event_id: UUID) -> QuerySet[CTFParticipant]:
    """List all participants for an event.

    Args:
        event_id: UUID of the event.

    Returns:
        QuerySet of CTFParticipant instances.
    """
    return CTFParticipant.objects.filter(event_id=event_id).select_related("team", "user", "bracket").order_by("name")


def get_participant(participant_id: UUID) -> CTFParticipant:
    """Get a participant by ID.

    Args:
        participant_id: UUID of the participant.

    Returns:
        The CTFParticipant instance.

    Raises:
        CTFNotFoundError: If participant doesn't exist.
    """
    try:
        return CTFParticipant.objects.select_related("event", "team", "user").get(pk=participant_id)
    except CTFParticipant.DoesNotExist:
        raise CTFNotFoundError(
            f"Participant {participant_id} not found",
            details={"participant_id": str(participant_id)},
        ) from None
