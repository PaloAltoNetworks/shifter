"""Scoreboard views for the canonical CTF API (per-participant timeline + organizer scoreboard)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ctf.api._base import CTF_ORGANIZER_PERMISSIONS, CTF_ROLE_PERMISSIONS, _CtfApiError
from ctf.api.organizer._base import (
    _EVENT_OR_PLAY_READ,
    _EVENT_READ,
    _PARTICIPANT_NOT_FOUND,
    _actor,
    _actor_may_manage,
    _raise_forbidden,
    _raise_not_found,
    _resolve_owned_event,
)
from ctf.api.serializers import (
    OrganizerScoreboardResponseSerializer,
    ScoreTimelineResponseSerializer,
)

if TYPE_CHECKING:
    from uuid import UUID

    from ctf.models import CTFParticipant


class ScoreTimelineView(APIView):
    """Return a participant's chronological score progression (role-based access)."""

    permission_classes = CTF_ROLE_PERMISSIONS
    required_read_scopes = _EVENT_OR_PLAY_READ

    @extend_schema(responses=ScoreTimelineResponseSerializer)
    def get(self, request: Request, participant_id: UUID) -> Response:
        """Resolve the participant, authorize access, and return the timeline."""
        from ctf.exceptions import CTFNotFoundError
        from ctf.services import get_participant
        from ctf.services.scoring import get_score_timeline

        try:
            try:
                participant = get_participant(participant_id)
            except CTFNotFoundError:
                _raise_not_found(_PARTICIPANT_NOT_FOUND)
            self._authorize(request, participant)
            timeline = get_score_timeline(participant_id)
            return Response(
                {
                    "participant_id": str(participant.id),
                    "participant_name": participant.name,
                    "timeline": timeline,
                }
            )
        except _CtfApiError as exc:
            return exc.to_response(request)

    @staticmethod
    def _authorize(request: Request, participant: CTFParticipant) -> None:
        """Authorize timeline access; organizers need event ownership, participants their own row.

        Mirrors ``ctf.views.api.scoreboard._authorize_timeline_access``.
        """
        from ctf.bridges import get_user_role

        actor = _actor(request)
        role = get_user_role(actor)
        if role.is_ctf_organizer:
            if not _actor_may_manage(request, participant.event, "submissions"):
                _raise_forbidden()
            return
        if participant.user_id != actor.pk:
            _raise_forbidden()


class OrganizerScoreboardView(APIView):
    """Full owned-event scoreboard for organizer monitoring.

    Unlike the public :class:`ctf.api.views.PublicScoreboardView`, this endpoint
    always returns the complete ranking payload: it ignores the event's
    ``scoreboard_visible`` flag and its freeze window (``freeze_at=None``), so an
    organizer monitoring a live event always sees real-time rankings. ``frozen``
    is reported for display only. Mirrors the legacy ``ctf.views.admin_people``
    ``admin_scoreboard`` build (team_mode + optional bracket filter).
    """

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_read_scopes = _EVENT_READ

    @extend_schema(operation_id="ctf_organizer_scoreboard", responses=OrganizerScoreboardResponseSerializer)
    def get(self, request: Request, event_id: UUID) -> Response:
        """Return the full scoreboard for an owned event, ignoring freeze/visibility."""
        from ctf.services.scoring import get_scoreboard, get_team_scoreboard
        from ctf.views import _parsing

        try:
            event = _resolve_owned_event(request, event_id)
        except _CtfApiError as exc:
            return exc.to_response(request)

        bracket_param = request.query_params.get("bracket")
        brackets, _selected_bracket, bracket_id = _parsing._resolve_bracket_filter(event.id, bracket_param)
        rankings = (
            get_team_scoreboard(event.id, freeze_at=None)
            if event.team_mode
            else get_scoreboard(event.id, freeze_at=None)
        )
        bracket_rankings = None
        if bracket_id:
            bracket_rankings = (
                get_team_scoreboard(event.id, freeze_at=None, bracket_id=bracket_id)
                if event.team_mode
                else get_scoreboard(event.id, freeze_at=None, bracket_id=bracket_id)
            )
        return Response(
            {
                "event_id": str(event.id),
                "team_mode": event.team_mode,
                "frozen": event.is_scoreboard_frozen,
                "rankings": rankings,
                "bracket_rankings": bracket_rankings,
                "brackets": [{"id": str(bracket.id), "name": bracket.name} for bracket in brackets],
            }
        )
