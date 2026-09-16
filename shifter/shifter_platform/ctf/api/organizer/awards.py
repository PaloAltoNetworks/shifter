"""Organizer award endpoints: grant, list, and revoke bonus/deduction points (CTF-204)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ctf.api._base import CTF_ORGANIZER_PERMISSIONS, _CtfApiError
from ctf.api.organizer._audit import (
    audit_admin_event_mutation,
)
from ctf.api.organizer._base import (
    _EVENT_READ,
    _EVENT_WRITE,
    _actor_may_manage,
    _raise_not_found,
    _resolve_owned_participant,
)
from ctf.api.serializers import (
    AwardListResponseSerializer,
    AwardSerializer,
    AwardWriteSerializer,
    ParticipantDeleteResultSerializer,
)
from shared.audit import AuditAction

if TYPE_CHECKING:
    from uuid import UUID

    from ctf.models import CTFAward

_AWARD_NOT_FOUND = "Award not found"


def _award_payload(award: CTFAward) -> dict[str, object]:
    """Serialize one award row for the organizer surface."""
    return {
        "id": str(award.id),
        "points": award.points,
        "reason": award.reason,
        "granted_by": award.granted_by.get_username() if award.granted_by else None,
        "created_at": award.created_at.isoformat() if award.created_at else None,
    }


class ParticipantAwardsView(APIView):
    """List (GET) or grant (POST) awards for an owned participant."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_read_scopes = _EVENT_READ
    required_write_scopes = _EVENT_WRITE

    @extend_schema(responses=AwardListResponseSerializer)
    def get(self, request: Request, participant_id: UUID) -> Response:
        """Return the participant's awards, newest first."""
        from ctf.services.award import get_participant_awards

        try:
            _resolve_owned_participant(request, participant_id, capability="awards")
        except _CtfApiError as exc:
            return exc.to_response(request)
        awards = [_award_payload(award) for award in get_participant_awards(participant_id)]
        return Response({"awards": awards})

    @extend_schema(request=AwardWriteSerializer, responses=AwardSerializer)
    @audit_admin_event_mutation("award.grant", action=AuditAction.CREATE)
    def post(self, request: Request, participant_id: UUID) -> Response:
        """Grant a bonus or deduction to the participant and recompute scores."""
        from ctf.services.award import grant_award

        try:
            participant = _resolve_owned_participant(request, participant_id, capability="awards")
        except _CtfApiError as exc:
            return exc.to_response(request)
        serializer = AwardWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        award = grant_award(
            event_id=participant.event_id,
            participant_id=participant_id,
            points=serializer.validated_data["points"],
            reason=serializer.validated_data["reason"],
            granted_by=request.user,
        )
        return Response(_award_payload(award), status=status.HTTP_201_CREATED)


class AwardRevokeView(APIView):
    """Revoke (POST) an award on an owned participant."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_write_scopes = _EVENT_WRITE

    @extend_schema(request=None, responses=ParticipantDeleteResultSerializer)
    @audit_admin_event_mutation("award.revoke", action=AuditAction.DELETE)
    def post(self, request: Request, award_id: UUID) -> Response:
        """Delete the award and recompute the affected scores."""
        from ctf.exceptions import CTFNotFoundError
        from ctf.models import CTFAward
        from ctf.services.award import revoke_award

        award = CTFAward.objects.filter(pk=award_id).select_related("event").first()
        if award is None or not _actor_may_manage(request, award.event, "awards"):
            # One not-found shape for missing and unowned rows (non-enumerating).
            try:
                _raise_not_found(_AWARD_NOT_FOUND)
            except _CtfApiError as exc:
                return exc.to_response(request)
        try:
            revoke_award(award_id)
        except CTFNotFoundError:
            try:
                _raise_not_found(_AWARD_NOT_FOUND)
            except _CtfApiError as exc:
                return exc.to_response(request)
        return Response({"deleted": True, "id": str(award_id)})
