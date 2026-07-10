"""Scoreboard and score-timeline JSON API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET

if TYPE_CHECKING:
    from django.http import HttpRequest

    from ctf.models import (
        CTFEvent,
        CTFParticipant,
    )

from ctf.views import _access, _parsing
from ctf.views._access import (
    _check_event_ownership,
    _get_user,
    ctf_role_required,
)

logger = logging.getLogger(__name__)


def _resolve_scoreboard_access(
    request: HttpRequest, event_id: UUID
) -> tuple[CTFEvent | None, bool, JsonResponse | None]:
    """Resolve the event and authorize scoreboard access; return (event, is_organizer, error_response).

    Issue #768: ``@ctf_role_required`` only proves the caller has *some* CTF
    role; it does not prove access to *this* event. Require organizer
    ownership OR registered, non-disqualified participant membership of this
    specific event before exposing scoreboard data. The 404-before-403
    ordering preserves the existing "no enumeration" shape for unknown UUIDs.
    Codex review pointed out that a bare ``registered_at__isnull=False`` filter
    would admit DISQUALIFIED participants — ``is_active_participant`` aligns the
    gate with the ``status__in`` filter the scoring service uses.
    """
    from ctf.exceptions import CTFNotFoundError
    from ctf.services import get_event
    from ctf.services.participant import is_active_participant

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        return None, False, JsonResponse({"error": "Event not found"}, status=404)

    user = _get_user(request)
    role = _access.get_user_role(user)
    is_organizer = role.is_ctf_organizer and event.created_by_id == user.pk
    if not is_organizer and not is_active_participant(user, event=event):
        logger.warning(
            "CTF scoreboard access denied for user %s on event %s",
            user.email,
            event.id,
        )
        return None, False, JsonResponse({"error": "Forbidden"}, status=403)

    return event, is_organizer, None


@login_required
@ctf_role_required
@require_GET
def api_scoreboard(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """API: Get scoreboard data.

    Supports bracket filtering via ?bracket=<uuid> query parameter.

    Args:
        event_id: UUID of the event.
    """
    from ctf.services.scoring import get_scoreboard, get_team_scoreboard

    event, is_organizer, error = _resolve_scoreboard_access(request, event_id)
    if error is not None:
        return error
    assert event is not None

    # If scoreboard is hidden from participants, return early
    if not is_organizer and not event.scoreboard_visible:
        return JsonResponse({"scoreboard_hidden": True})

    freeze_at = None
    if not is_organizer and event.is_scoreboard_frozen:
        freeze_at = event.scoreboard_freeze_at

    brackets, _selected_bracket, bracket_id = _parsing._resolve_bracket_filter(event.id, request.GET.get("bracket"))

    rankings = (
        get_team_scoreboard(event.id, freeze_at=freeze_at)
        if event.team_mode
        else get_scoreboard(event.id, freeze_at=freeze_at)
    )

    bracket_rankings = None
    if bracket_id:
        bracket_rankings = (
            get_team_scoreboard(event.id, freeze_at=freeze_at, bracket_id=bracket_id)
            if event.team_mode
            else get_scoreboard(event.id, freeze_at=freeze_at, bracket_id=bracket_id)
        )

    brackets_data = [{"id": str(b.id), "name": b.name} for b in brackets]

    return JsonResponse(
        {
            "event_id": str(event.id),
            "team_mode": event.team_mode,
            "frozen": event.is_scoreboard_frozen and not is_organizer,
            "rankings": rankings,
            "bracket_rankings": bracket_rankings,
            "brackets": brackets_data,
        }
    )


def _authorize_timeline_access(request: HttpRequest, participant: CTFParticipant) -> JsonResponse | None:
    """Authorize score-timeline access; organizers need event ownership, participants their own row."""
    user = _get_user(request)
    role = _access.get_user_role(user)
    if role.is_ctf_organizer:
        return _check_event_ownership(participant.event, user)
    if participant.user_id != user.pk:
        return JsonResponse({"error": "Forbidden"}, status=403)
    return None


@login_required
@ctf_role_required
@require_GET
def api_score_timeline(request: HttpRequest, participant_id: UUID) -> JsonResponse:
    """API: Get per-participant score timeline.

    Returns chronological score progression data for rendering a step chart.
    Participants can view their own timeline; organizers can view any
    participant's timeline for events they own.

    Args:
        participant_id: UUID of the participant.
    """
    from ctf.exceptions import CTFNotFoundError
    from ctf.services import get_participant
    from ctf.services.scoring import get_score_timeline

    try:
        participant = get_participant(participant_id)
    except CTFNotFoundError:
        return JsonResponse({"error": "Participant not found"}, status=404)

    auth_error = _authorize_timeline_access(request, participant)
    if auth_error is not None:
        return auth_error

    timeline = get_score_timeline(participant_id)

    return JsonResponse(
        {
            "participant_id": str(participant.id),
            "participant_name": participant.name,
            "timeline": timeline,
        }
    )
