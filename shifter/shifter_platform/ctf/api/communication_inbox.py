"""Session-only communication inbox; reads never mutate participant receipts."""

from __future__ import annotations

from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ctf.api._base import ctf_error_response
from ctf.api.communication_schema import SessionCommunicationSchema
from ctf.api.organizer.communication import validate_query
from ctf.api.serializers.communication import (
    CommunicationEmptySerializer,
    CommunicationInboxItemSerializer,
    CommunicationJSONParser,
)
from ctf.exceptions import CTFCommunicationError
from ctf.services.communication.inbox import inbox_for_participant, interact_with_receipt
from shared.api.closed_serializer import ClosedSerializer
from shared.api.permissions import IsAuthenticatedSession


class InboxQuerySerializer(ClosedSerializer):
    """Bound the participant inbox page size and offset."""

    limit = serializers.IntegerField(min_value=1, max_value=100, default=25)
    offset = serializers.IntegerField(min_value=0, max_value=100000, default=0)


class InboxPageSerializer(serializers.Serializer):
    """Project one inbox page and its continuation offset."""

    results = CommunicationInboxItemSerializer(many=True)
    next_offset = serializers.IntegerField(allow_null=True)


class InboxView(APIView):
    """Apply session-only policy and canonical inbox error responses."""

    schema = SessionCommunicationSchema()
    permission_classes = [IsAuthenticatedSession]
    parser_classes = [CommunicationJSONParser]

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, CTFCommunicationError):
            return ctf_error_response(self.request, exc)
        return super().handle_exception(exc)


class CommunicationInboxView(InboxView):
    """List retained messages for the current participant and event."""

    @extend_schema(
        operation_id="ctf_communication_inbox_list",
        parameters=[InboxQuerySerializer],
        responses=InboxPageSerializer,
    )
    def get(self, request: Request, event_id: UUID) -> Response:
        query = validate_query(request, InboxQuerySerializer)
        start, limit = query["offset"], query["limit"]
        rows = list(inbox_for_participant(request.user, event_id)[start : start + limit + 1])
        return Response(
            {
                "results": CommunicationInboxItemSerializer(rows[:limit], many=True).data,
                "next_offset": start + limit if len(rows) > limit else None,
            }
        )


class CommunicationInboxDetailView(InboxView):
    """Fetch one message within the authorized participant inbox."""

    @extend_schema(responses=CommunicationInboxItemSerializer)
    def get(self, request: Request, event_id: UUID, snapshot_id: UUID) -> Response:
        validate_query(request, CommunicationEmptySerializer)
        snapshot = inbox_for_participant(request.user, event_id).filter(pk=snapshot_id).first()
        if snapshot is None:
            raise CTFCommunicationError("Unavailable", code="CTF_COMMUNICATION_NOT_FOUND")
        return Response(CommunicationInboxItemSerializer(snapshot).data)


class CommunicationReadView(InboxView):
    """Record an explicit, idempotent read interaction."""

    acknowledge = False

    @extend_schema(request=CommunicationEmptySerializer, responses=CommunicationInboxItemSerializer)
    def post(self, request: Request, event_id: UUID, snapshot_id: UUID) -> Response:
        validate_query(request, CommunicationEmptySerializer)
        serializer = CommunicationEmptySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        snapshot = interact_with_receipt(request.user, event_id, snapshot_id, acknowledge=self.acknowledge)
        return Response(CommunicationInboxItemSerializer(snapshot).data)


class CommunicationAcknowledgeView(CommunicationReadView):
    """Record acknowledgement under the pinned message policy."""

    acknowledge = True
