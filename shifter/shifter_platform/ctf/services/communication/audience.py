"""The single audience resolver for scoped communications (ADR-051, #2048).

One closed resolver turns a validated :class:`AudienceKind` selector into a
deterministic, deduplicated, event-qualified set of viewing-eligible
participants. Views, schedulers, and (later) RAES adapters must resolve through
here so audience policy never drifts across surfaces (AC7). Recipient authority
is the event-scoped ``CTFParticipant`` reached through the shared
``viewing_participant_q`` predicate -- never an email address or ambient user.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from ctf.communication_contracts import validate_audience_spec
from ctf.enums_communication import AudienceKind
from ctf.exceptions import CTFCommunicationError
from ctf.models import CTFParticipant
from ctf.services.participant.queries import viewing_participant_q


def _as_uuids(values: list[str]) -> list[UUID]:
    """Parse a list of validated UUID strings into ``UUID`` objects."""
    return [UUID(value) for value in values]


def resolve_recipients(target_event_ids: set[UUID], audience_spec: dict[str, Any]) -> list[CTFParticipant]:
    """Resolve a closed audience selector to event-qualified recipients.

    Returns viewing-eligible participants ordered by their immutable id so the
    result is deterministic and, because each participant is a single
    event-scoped row, inherently deduplicated. Every recipient is restricted to
    ``target_event_ids``; an audience that names an event outside the campaign's
    targets is rejected, and participants/teams outside the targets simply do not
    resolve (no cross-tenant membership oracle).
    """
    spec = validate_audience_spec(audience_spec)
    kind = spec["kind"]
    base = CTFParticipant.objects.filter(viewing_participant_q(), event_id__in=target_event_ids)

    if kind in (AudienceKind.PARTICIPANT.value, AudienceKind.PARTICIPANT_SET.value):
        qs = base.filter(id__in=_as_uuids(spec["participant_ids"]))
    elif kind == AudienceKind.TEAM.value:
        qs = base.filter(team_id__in=_as_uuids(spec["team_ids"]))
    else:
        # EVENT or MULTI_EVENT
        event_ids = _as_uuids(spec["event_ids"])
        if not set(event_ids) <= set(target_event_ids):
            raise CTFCommunicationError(
                "Audience references an event outside the campaign targets",
                code="CTF_COMMUNICATION_AUDIENCE_OUT_OF_SCOPE",
            )
        qs = base.filter(event_id__in=event_ids)

    return list(qs.select_related("event", "team", "user").order_by("id"))
