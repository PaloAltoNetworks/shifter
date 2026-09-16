"""Participant moderation: ban, disqualify, role, and visibility changes.

CTF-604/605/606/609. Every transition here recomputes the participant's team
materialized score when they belong to one, because each of these states
changes whether the participant's rows count toward rankings.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.db import transaction

from ctf.enums import ParticipantRole, ParticipantStatus
from ctf.exceptions import CTFNotFoundError, CTFStateError, CTFValidationError
from ctf.models import CTFParticipant

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger(__name__)


def _locked_participant(participant_id: UUID) -> CTFParticipant:
    """Load a live participant row under a row lock, or raise not-found.

    Callers run inside ``transaction.atomic``; the lock serializes concurrent
    moderation actions and the team-score recomputes they trigger.
    """
    try:
        return (
            CTFParticipant.objects.select_for_update(of=("self",))
            .select_related("event")
            .get(pk=participant_id, deleted_at__isnull=True)
        )
    except CTFParticipant.DoesNotExist:
        raise CTFNotFoundError(
            f"Participant {participant_id} not found",
            details={"participant_id": str(participant_id)},
        ) from None


def _recompute_team(participant: CTFParticipant) -> None:
    """Refresh the materialized team score after an eligibility-affecting change."""
    if participant.team_id is not None:
        from ctf.services.scoring import recompute_team_score

        recompute_team_score(participant.team_id)


def _restored_status() -> str:
    """Status to restore after lifting a ban or disqualification.

    Every participant is provisioned and registered on creation, so restoration
    always lands on ``registered``; activity tracking moves it forward again.
    """
    return ParticipantStatus.REGISTERED.value


def ban_participant(participant_id: UUID, reason: str | None = None) -> CTFParticipant:
    """Ban a participant from their event (CTF-605).

    A banned participant fails both the compete and view predicates, so every
    event surface (content, submission, scoreboard) rejects them. Their
    account and submission history are preserved for audit and for
    :func:`unban_participant`.
    """
    with transaction.atomic():
        participant = _locked_participant(participant_id)
        if participant.status == ParticipantStatus.BANNED.value:
            raise CTFStateError("Participant is already banned", details={"participant_id": str(participant_id)})
        participant.status = ParticipantStatus.BANNED.value
        participant.status_reason = (reason or "").strip()
        participant.save(update_fields=["status", "status_reason", "updated_at"])
        _recompute_team(participant)
    logger.info("Banned participant %s", participant_id)
    return participant


def unban_participant(participant_id: UUID) -> CTFParticipant:
    """Lift a ban, restoring registration-derived status (CTF-605)."""
    with transaction.atomic():
        participant = _locked_participant(participant_id)
        if participant.status != ParticipantStatus.BANNED.value:
            raise CTFStateError("Participant is not banned", details={"participant_id": str(participant_id)})
        participant.status = _restored_status()
        participant.status_reason = ""
        participant.save(update_fields=["status", "status_reason", "updated_at"])
        _recompute_team(participant)
    logger.info("Unbanned participant %s", participant_id)
    return participant


def disqualify_participant(participant_id: UUID, reason: str | None = None) -> CTFParticipant:
    """Disqualify a participant (CTF-609): out of rankings, view access kept.

    Softer than a ban — the participant's account stays live so they can
    still browse event content, but the compete predicate now rejects them
    (no submissions, no rank) and their team sheds their contribution.
    Reversible via :func:`requalify_participant`.
    """
    with transaction.atomic():
        participant = _locked_participant(participant_id)
        if participant.status == ParticipantStatus.DISQUALIFIED.value:
            raise CTFStateError("Participant is already disqualified", details={"participant_id": str(participant_id)})
        participant.status = ParticipantStatus.DISQUALIFIED.value
        participant.status_reason = (reason or "").strip()
        participant.save(update_fields=["status", "status_reason", "updated_at"])
        _recompute_team(participant)
    logger.info("Disqualified participant %s: %s", participant_id, reason or "No reason provided")
    return participant


def requalify_participant(participant_id: UUID) -> CTFParticipant:
    """Reverse a disqualification (CTF-609), restoring competitive standing."""
    with transaction.atomic():
        participant = _locked_participant(participant_id)
        if participant.status != ParticipantStatus.DISQUALIFIED.value:
            raise CTFStateError("Participant is not disqualified", details={"participant_id": str(participant_id)})
        participant.status = _restored_status()
        participant.status_reason = ""
        participant.save(update_fields=["status", "status_reason", "updated_at"])
        _recompute_team(participant)
    logger.info("Requalified participant %s", participant_id)
    return participant


def set_participant_role(participant_id: UUID, role: str) -> CTFParticipant:
    """Set the event-scoped participation role (CTF-604): player or observer."""
    valid_roles = {r.value for r in ParticipantRole}
    if role not in valid_roles:
        raise CTFValidationError(
            "Invalid participant role",
            code="CTF_INVALID_ROLE",
            details={"role": role, "valid": sorted(valid_roles)},
        )
    with transaction.atomic():
        participant = _locked_participant(participant_id)
        if participant.role != role:
            participant.role = role
            participant.save(update_fields=["role", "updated_at"])
            _recompute_team(participant)
    logger.info("Set participant %s role to %s", participant_id, role)
    return participant


def set_participant_hidden(participant_id: UUID, hidden: bool) -> CTFParticipant:
    """Show or hide a participant on rankings (CTF-606); play is unaffected."""
    with transaction.atomic():
        participant = _locked_participant(participant_id)
        if participant.hidden != hidden:
            participant.hidden = hidden
            participant.save(update_fields=["hidden", "updated_at"])
            _recompute_team(participant)
    logger.info("Set participant %s hidden=%s", participant_id, hidden)
    return participant
