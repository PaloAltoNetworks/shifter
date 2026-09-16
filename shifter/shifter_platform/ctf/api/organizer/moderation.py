"""Organizer participant-moderation views (CTF-604/605/606/609, #1206 rename).

Small POST actions on one participant: ban/unban, disqualify/requalify, role,
hidden, and username rename. All are delegable to moderators via the
``participants`` capability (CTF-607).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ctf.api._base import CTF_ORGANIZER_PERMISSIONS, _CtfApiError
from ctf.api.organizer._audit import (
    _audit_admin_from_request,
)
from ctf.api.organizer._base import (
    _EVENT_WRITE,
    _actor,
    _participant_detail_payload,
    _raise_bad_request,
    _raise_conflict,
    _resolve_owned_participant,
)
from ctf.api.serializers import (
    ParticipantDetailSerializer,
    ParticipantHiddenRequestSerializer,
    ParticipantModerationRequestSerializer,
    ParticipantRoleRequestSerializer,
    ParticipantUsernameRequestSerializer,
)

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger(__name__)


class _ModerationActionView(APIView):
    """Shared shell: resolve the participant with staff capability, run one action."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_write_scopes = _EVENT_WRITE
    request_serializer: type | None = None

    def _run(
        self,
        request: Request,
        participant_id: UUID,
        action: Any,
    ) -> Response:
        """Authorize, validate the optional body, apply, and return the detail payload."""
        from django.db import transaction

        from ctf.exceptions import CTFStateError, CTFValidationError

        try:
            _resolve_owned_participant(request, participant_id, capability="participants")
            body: dict[str, Any] = {}
            if self.request_serializer is not None:
                serializer = self.request_serializer(data=request.data)
                serializer.is_valid(raise_exception=True)
                body = dict(serializer.validated_data)
            # Database-only moderation action; the action and its platform-admin
            # override audit share one transaction (ADR-052-R4). ``_run`` is the
            # single point of repair for every moderation view.
            with transaction.atomic():
                try:
                    participant = action(body)
                except CTFStateError as exc:
                    _raise_conflict(str(exc))
                except CTFValidationError as exc:
                    _raise_bad_request(str(exc))
                _audit_admin_from_request(request, "participant.moderate")
            return Response(_participant_detail_payload(participant))
        except _CtfApiError as exc:
            return exc.to_response(request)


class ParticipantBanView(_ModerationActionView):
    """Ban a participant from the event (POST, CTF-605)."""

    request_serializer = ParticipantModerationRequestSerializer

    @extend_schema(request=ParticipantModerationRequestSerializer, responses=ParticipantDetailSerializer)
    def post(self, request: Request, participant_id: UUID) -> Response:
        """Ban with an optional recorded reason."""
        from ctf.services import ban_participant

        return self._run(request, participant_id, lambda body: ban_participant(participant_id, body.get("reason")))


class ParticipantUnbanView(_ModerationActionView):
    """Lift a participant ban (POST, CTF-605)."""

    @extend_schema(request=None, responses=ParticipantDetailSerializer)
    def post(self, request: Request, participant_id: UUID) -> Response:
        """Restore the registration-derived status."""
        from ctf.services import unban_participant

        return self._run(request, participant_id, lambda _body: unban_participant(participant_id))


class ParticipantDisqualifyView(_ModerationActionView):
    """Disqualify a participant (POST, CTF-609)."""

    request_serializer = ParticipantModerationRequestSerializer

    @extend_schema(request=ParticipantModerationRequestSerializer, responses=ParticipantDetailSerializer)
    def post(self, request: Request, participant_id: UUID) -> Response:
        """Disqualify with an optional recorded reason."""
        from ctf.services import disqualify_participant

        return self._run(
            request, participant_id, lambda body: disqualify_participant(participant_id, body.get("reason"))
        )


class ParticipantRequalifyView(_ModerationActionView):
    """Reverse a disqualification (POST, CTF-609)."""

    @extend_schema(request=None, responses=ParticipantDetailSerializer)
    def post(self, request: Request, participant_id: UUID) -> Response:
        """Restore competitive standing."""
        from ctf.services import requalify_participant

        return self._run(request, participant_id, lambda _body: requalify_participant(participant_id))


class ParticipantRoleView(_ModerationActionView):
    """Set the event-scoped participation role (POST, CTF-604)."""

    request_serializer = ParticipantRoleRequestSerializer

    @extend_schema(request=ParticipantRoleRequestSerializer, responses=ParticipantDetailSerializer)
    def post(self, request: Request, participant_id: UUID) -> Response:
        """Switch between player and observer."""
        from ctf.services import set_participant_role

        return self._run(request, participant_id, lambda body: set_participant_role(participant_id, body["role"]))


class ParticipantHiddenView(_ModerationActionView):
    """Toggle scoreboard visibility (POST, CTF-606)."""

    request_serializer = ParticipantHiddenRequestSerializer

    @extend_schema(request=ParticipantHiddenRequestSerializer, responses=ParticipantDetailSerializer)
    def post(self, request: Request, participant_id: UUID) -> Response:
        """Hide or show the participant on rankings."""
        from ctf.services import set_participant_hidden

        return self._run(request, participant_id, lambda body: set_participant_hidden(participant_id, body["hidden"]))


class ParticipantUsernameView(_ModerationActionView):
    """Rename a participant's login handle (POST, #1206 canonical parity)."""

    request_serializer = ParticipantUsernameRequestSerializer

    @extend_schema(request=ParticipantUsernameRequestSerializer, responses=ParticipantDetailSerializer)
    def post(self, request: Request, participant_id: UUID) -> Response:
        """Rename after organizer/moderator authorization inside the service."""
        from ctf.services.participant import rename_participant_username

        return self._run(
            request,
            participant_id,
            lambda body: rename_participant_username(participant_id, body["username"], actor=_actor(request)),
        )
