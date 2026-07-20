"""Participant team lifecycle: create, join, leave, and captain actions (CTF-501..506).

The join path carries the #1140 hardening: the capacity check and the
membership write happen under a ``select_for_update`` row lock on the team, so
concurrent joins cannot race past ``team_size_limit``. Captain-only actions
authorize on the acting participant being the team's captain.
"""

from __future__ import annotations

import logging
import secrets
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction

from ctf.exceptions import CTFNotFoundError, CTFPermissionError, CTFStateError, CTFValidationError
from ctf.models import CTFParticipant, CTFTeam

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger(__name__)

_TEAM_NAME_MAX_LENGTH = 100


def _load_participant(participant_id: UUID) -> CTFParticipant:
    """Load a compete-eligible participant with their event, or raise.

    Team membership shapes scoring, so every team action is a competitive
    action: the shared compete assert refuses disqualified/banned rows and
    observers (CTF-604/605/609) even though the read surface admits them.
    """
    from ctf.services.participant import assert_participant_can_compete

    participant = CTFParticipant.objects.select_related("event", "team").filter(pk=participant_id).first()
    if participant is None or participant.registered_at is None:
        raise CTFNotFoundError(
            "Participant not found",
            details={"participant_id": str(participant_id)},
        )
    assert_participant_can_compete(participant)
    return participant


def _require_team_mode(participant: CTFParticipant) -> None:
    """Reject team actions on solo events."""
    if not participant.event.team_mode:
        raise CTFStateError(
            "This event does not use teams",
            details={"event_id": str(participant.event_id)},
        )


def _validated_team_name(name: str) -> str:
    """Normalize and bound a requested team name."""
    cleaned = (name or "").strip()
    if not cleaned or len(cleaned) > _TEAM_NAME_MAX_LENGTH:
        raise CTFValidationError(
            "Team name must be between 1 and 100 characters",
            details={"name_length": len(cleaned)},
        )
    return cleaned


def _require_captain(participant: CTFParticipant) -> CTFTeam:
    """Return the participant's team when they captain it, else raise."""
    team = participant.team
    if team is None:
        raise CTFStateError("You are not on a team", details={"participant_id": str(participant.pk)})
    if team.captain_id != participant.pk:
        raise CTFPermissionError(
            "Only the team captain can do this",
            details={"team_id": str(team.pk)},
        )
    return team


def _recompute_team(team_id: UUID | None) -> None:
    """Refresh a team's materialized score columns after membership changes (#850)."""
    if team_id is None:
        return
    from ctf.services.scoring import recompute_team_score

    recompute_team_score(team_id)


def create_team(participant_id: UUID, name: str) -> CTFTeam:
    """Create a team in the participant's event; the creator becomes captain.

    The unique-name-per-event constraint is the race backstop: a concurrent
    create with the same name surfaces as a controlled validation error.
    """
    participant = _load_participant(participant_id)
    _require_team_mode(participant)
    if participant.team_id is not None:
        raise CTFStateError(
            "Leave your current team before creating a new one",
            details={"team_id": str(participant.team_id)},
        )
    cleaned = _validated_team_name(name)
    try:
        with transaction.atomic():
            team = CTFTeam.objects.create(
                event=participant.event,
                name=cleaned,
                captain=participant,
            )
            participant.team = team
            participant.save(update_fields=["team", "updated_at"])
            _recompute_team(team.pk)
    except (IntegrityError, DjangoValidationError) as exc:
        raise CTFValidationError(
            "A team with this name already exists in this event",
            details={"name": cleaned},
        ) from exc
    logger.info("Participant %s created team %s in event %s", participant.pk, team.pk, participant.event_id)
    return team


def join_team(participant_id: UUID, invite_code: str) -> CTFTeam:
    """Join a team by invite code with the #1140 capacity guard.

    Locks the team row, re-checks ``is_full`` under the lock, then writes, so
    concurrent joins serialize and the size limit holds.
    """
    participant = _load_participant(participant_id)
    _require_team_mode(participant)
    code = (invite_code or "").strip()
    if not code:
        raise CTFValidationError("Invite code is required")
    team = CTFTeam.objects.filter(event=participant.event, invite_code=code).first()
    if team is None:
        raise CTFNotFoundError("Invalid invite code")
    if participant.team_id == team.pk:
        raise CTFStateError("You are already on this team", details={"team_id": str(team.pk)})
    with transaction.atomic():
        locked_team = CTFTeam.objects.select_for_update().get(pk=team.pk)
        if locked_team.is_full:
            raise CTFStateError("This team is full", details={"team_id": str(team.pk)})
        old_team_id = participant.team_id
        participant.team = locked_team
        participant.save(update_fields=["team", "updated_at"])
        _recompute_team(locked_team.pk)
        if old_team_id is not None and old_team_id != locked_team.pk:
            _recompute_team(old_team_id)
    logger.info("Participant %s joined team %s in event %s", participant.pk, team.pk, participant.event_id)
    return team


def leave_team(participant_id: UUID) -> None:
    """Leave the current team.

    A captain with teammates must transfer captaincy (or disband) first; a
    captain who is the last member disbands the team by leaving.
    """
    participant = _load_participant(participant_id)
    team = participant.team
    if team is None:
        raise CTFStateError("You are not on a team", details={"participant_id": str(participant.pk)})
    with transaction.atomic():
        locked_team = CTFTeam.objects.select_for_update().get(pk=team.pk)
        member_count = locked_team.members.count()
        if locked_team.captain_id == participant.pk and member_count > 1:
            raise CTFStateError(
                "Transfer captaincy or disband the team before leaving",
                details={"team_id": str(locked_team.pk)},
            )
        participant.team = None
        participant.save(update_fields=["team", "updated_at"])
        if member_count <= 1:
            locked_team.delete()
        else:
            _recompute_team(locked_team.pk)
    logger.info("Participant %s left team %s", participant.pk, team.pk)


def rename_team(participant_id: UUID, name: str) -> CTFTeam:
    """Rename the team (captain only); uniqueness enforced per event."""
    participant = _load_participant(participant_id)
    team = _require_captain(participant)
    cleaned = _validated_team_name(name)
    team.name = cleaned
    try:
        team.save(update_fields=["name", "updated_at"])
    except (IntegrityError, DjangoValidationError) as exc:
        raise CTFValidationError(
            "A team with this name already exists in this event",
            details={"name": cleaned},
        ) from exc
    return team


def regenerate_invite_code(participant_id: UUID) -> CTFTeam:
    """Mint a fresh invite code (captain only), invalidating the old one."""
    participant = _load_participant(participant_id)
    team = _require_captain(participant)
    team.invite_code = secrets.token_urlsafe(16)
    team.save(update_fields=["invite_code", "updated_at"])
    logger.info("Captain %s regenerated the invite code for team %s", participant.pk, team.pk)
    return team


def transfer_captaincy(participant_id: UUID, new_captain_participant_id: UUID) -> CTFTeam:
    """Hand captaincy to a teammate (captain only)."""
    participant = _load_participant(participant_id)
    team = _require_captain(participant)
    new_captain = CTFParticipant.objects.filter(pk=new_captain_participant_id, team=team).first()
    if new_captain is None:
        raise CTFNotFoundError(
            "New captain must be a member of your team",
            details={"participant_id": str(new_captain_participant_id)},
        )
    team.captain = new_captain
    team.save(update_fields=["captain", "updated_at"])
    logger.info("Team %s captaincy transferred to participant %s", team.pk, new_captain.pk)
    return team


def remove_member(participant_id: UUID, member_participant_id: UUID) -> CTFTeam:
    """Remove a teammate from the team (captain only; not yourself)."""
    participant = _load_participant(participant_id)
    team = _require_captain(participant)
    if member_participant_id == participant.pk:
        raise CTFValidationError("Use leave or disband instead of removing yourself")
    member = CTFParticipant.objects.filter(pk=member_participant_id, team=team).first()
    if member is None:
        raise CTFNotFoundError(
            "Member not found on your team",
            details={"participant_id": str(member_participant_id)},
        )
    with transaction.atomic():
        member.team = None
        member.save(update_fields=["team", "updated_at"])
        _recompute_team(team.pk)
    logger.info("Captain %s removed participant %s from team %s", participant.pk, member.pk, team.pk)
    return team


def disband_team(participant_id: UUID) -> None:
    """Dissolve the team (captain only): unteam every member, delete the team."""
    participant = _load_participant(participant_id)
    team = _require_captain(participant)
    with transaction.atomic():
        locked_team = CTFTeam.objects.select_for_update().get(pk=team.pk)
        locked_team.members.update(team=None)
        locked_team.delete()
    logger.info("Captain %s disbanded team %s", participant.pk, team.pk)


__all__ = [
    "create_team",
    "disband_team",
    "join_team",
    "leave_team",
    "regenerate_invite_code",
    "remove_member",
    "rename_team",
    "transfer_captaincy",
]
