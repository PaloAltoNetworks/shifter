"""Canonical DRF participant team lifecycle views (CTF-501..506).

POST actions on the actor's own team: create, join by invite code, leave,
and the captain-only rename / regenerate-code / transfer / remove-member /
disband actions. Domain rules (team mode, capacity under the #1140 row lock,
captain authorization) live in :mod:`ctf.services.team`; these views resolve
the acting participant with the same event-scoped policy as the other
``/me/*`` reads and translate the ``CTFError`` family into the shared error
envelope.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ctf.api import projections
from ctf.api._base import CTF_PARTICIPANT_PERMISSIONS
from ctf.api.participant_views import _resolve_active_participant
from ctf.api.serializers import (
    ParticipantTeamSerializer,
    TeamCreateRequestSerializer,
    TeamJoinRequestSerializer,
    TeamMemberRequestSerializer,
)
from ctf.exceptions import CTFError, CTFNotFoundError, CTFPermissionError, CTFStateError, CTFValidationError
from shared.api.errors import api_error_response
from shared.api_tokens import scopes

if TYPE_CHECKING:
    from collections.abc import Callable

    from ctf.models import CTFParticipant

_NO_ACTIVE_EVENT = "No active CTF event for this participant."
_PLAY_WRITE = (scopes.CTF_PLAY_WRITE,)

_ERROR_STATUS = {
    CTFNotFoundError: status.HTTP_404_NOT_FOUND,
    CTFValidationError: status.HTTP_400_BAD_REQUEST,
    CTFPermissionError: status.HTTP_403_FORBIDDEN,
    CTFStateError: status.HTTP_409_CONFLICT,
}

_ERROR_CODE = {
    CTFNotFoundError: "not_found",
    CTFValidationError: "invalid",
    CTFPermissionError: "forbidden",
    CTFStateError: "conflict",
}


def _ctf_error_response(request: Request, exc: CTFError) -> Response:
    """Translate a ``CTFError`` into the shared API error envelope."""
    return api_error_response(
        code=_ERROR_CODE.get(type(exc), "conflict"),
        message=str(exc),
        status_code=_ERROR_STATUS.get(type(exc), status.HTTP_409_CONFLICT),
        request=request,
    )


def _no_participant_response(request: Request) -> Response:
    """404 for actors without an active CTF event."""
    return api_error_response(
        code="not_found",
        message=_NO_ACTIVE_EVENT,
        status_code=status.HTTP_404_NOT_FOUND,
        request=request,
    )


def _team_response(participant: CTFParticipant) -> Response:
    """Serialize the participant's refreshed team projection."""
    participant.refresh_from_db()
    team = projections.participant_team(participant)
    return Response(ParticipantTeamSerializer(team).data)


class _TeamActionView(APIView):
    """Shared plumbing for participant team POST actions."""

    permission_classes = CTF_PARTICIPANT_PERMISSIONS
    required_write_scopes = _PLAY_WRITE

    def _act(self, request: Request, action: Callable[[CTFParticipant], object]) -> Response:
        """Resolve the participant, run ``action(participant)``, shape the response."""
        participant = _resolve_active_participant(request)
        if participant is None:
            return _no_participant_response(request)
        try:
            action(participant)
        except CTFError as exc:
            return _ctf_error_response(request, exc)
        return _team_response(participant)


class TeamCreateView(_TeamActionView):
    """Create a team; the creator becomes captain."""

    @extend_schema(request=TeamCreateRequestSerializer, responses=ParticipantTeamSerializer)
    def post(self, request: Request) -> Response:
        """Create a team named by the request body."""
        from ctf.services.team import create_team

        serializer = TeamCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._act(request, lambda p: create_team(p.pk, serializer.validated_data["name"]))


class TeamJoinView(_TeamActionView):
    """Join a team by invite code (capacity-guarded, #1140)."""

    @extend_schema(request=TeamJoinRequestSerializer, responses=ParticipantTeamSerializer)
    def post(self, request: Request) -> Response:
        """Join the team matching the submitted invite code."""
        from ctf.services.team import join_team

        serializer = TeamJoinRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._act(request, lambda p: join_team(p.pk, serializer.validated_data["invite_code"]))


class TeamLeaveView(_TeamActionView):
    """Leave the current team."""

    @extend_schema(request=None, responses=None)
    def post(self, request: Request) -> Response:
        """Leave; a lone captain disbands the team by leaving."""
        from ctf.services.team import leave_team

        participant = _resolve_active_participant(request)
        if participant is None:
            return _no_participant_response(request)
        try:
            leave_team(participant.pk)
        except CTFError as exc:
            return _ctf_error_response(request, exc)
        return Response({"left": True})


class TeamRenameView(_TeamActionView):
    """Rename the team (captain only)."""

    @extend_schema(request=TeamCreateRequestSerializer, responses=ParticipantTeamSerializer)
    def post(self, request: Request) -> Response:
        """Rename to the requested unique-per-event name."""
        from ctf.services.team import rename_team

        serializer = TeamCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._act(request, lambda p: rename_team(p.pk, serializer.validated_data["name"]))


class TeamRegenerateCodeView(_TeamActionView):
    """Mint a fresh invite code (captain only)."""

    @extend_schema(request=None, responses=ParticipantTeamSerializer)
    def post(self, request: Request) -> Response:
        """Invalidate the old invite code and return the new one."""
        from ctf.services.team import regenerate_invite_code

        return self._act(request, lambda p: regenerate_invite_code(p.pk))


class TeamTransferCaptaincyView(_TeamActionView):
    """Hand captaincy to a teammate (captain only)."""

    @extend_schema(request=TeamMemberRequestSerializer, responses=ParticipantTeamSerializer)
    def post(self, request: Request) -> Response:
        """Transfer captaincy to the named teammate."""
        from ctf.services.team import transfer_captaincy

        serializer = TeamMemberRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._act(request, lambda p: transfer_captaincy(p.pk, serializer.validated_data["participant_id"]))


class TeamRemoveMemberView(_TeamActionView):
    """Remove a teammate (captain only)."""

    @extend_schema(request=TeamMemberRequestSerializer, responses=ParticipantTeamSerializer)
    def post(self, request: Request) -> Response:
        """Remove the named teammate from the team."""
        from ctf.services.team import remove_member

        serializer = TeamMemberRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._act(request, lambda p: remove_member(p.pk, serializer.validated_data["participant_id"]))


class TeamDisbandView(_TeamActionView):
    """Dissolve the team (captain only)."""

    @extend_schema(request=None, responses=None)
    def post(self, request: Request) -> Response:
        """Unteam every member and delete the team."""
        from ctf.services.team import disband_team

        participant = _resolve_active_participant(request)
        if participant is None:
            return _no_participant_response(request)
        try:
            disband_team(participant.pk)
        except CTFError as exc:
            return _ctf_error_response(request, exc)
        return Response({"disbanded": True})
