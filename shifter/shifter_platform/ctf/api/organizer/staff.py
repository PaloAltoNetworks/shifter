"""Event staff and ownership authority-topology views (CTF-607, #1922).

Staff management (moderators, judges, co-organizers) and canonical-ownership
transfer stay with the owning organizer — capability delegation never includes
delegating further, which is what keeps a co-organizer from escalating itself.
"""

from __future__ import annotations

import logging
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
    _actor,
    _raise_bad_request,
    _raise_not_found,
    _resolve_owned_event,
)
from ctf.api.serializers import (
    EventMutationResultSerializer,
    EventOwnershipTransferRequestSerializer,
    EventStaffAssignRequestSerializer,
    EventStaffListResponseSerializer,
    EventStaffMemberSerializer,
    ParticipantDeleteResultSerializer,
)
from shared.audit import AuditAction

if TYPE_CHECKING:
    from uuid import UUID

    from ctf.models import CTFEventStaff

logger = logging.getLogger(__name__)


def _staff_payload(staff: CTFEventStaff) -> dict[str, object]:
    """Render one staff assignment row."""
    return {
        "user_id": staff.user_id,
        "email": staff.user.email,
        "role": staff.role,
        "created_at": staff.created_at.isoformat() if staff.created_at else None,
    }


class EventStaffView(APIView):
    """List (GET) or assign (POST) delegated staff on an owned event."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_read_scopes = _EVENT_READ
    required_write_scopes = _EVENT_WRITE

    @extend_schema(responses=EventStaffListResponseSerializer)
    def get(self, request: Request, event_id: UUID) -> Response:
        """Return the event's staff assignments (owner-only)."""
        from ctf.services.event import list_event_staff

        try:
            _resolve_owned_event(request, event_id)
        except _CtfApiError as exc:
            return exc.to_response(request)
        return Response({"staff": [_staff_payload(s) for s in list_event_staff(event_id)]})

    @extend_schema(request=EventStaffAssignRequestSerializer, responses=EventStaffMemberSerializer)
    @audit_admin_event_mutation("staff.assign", action=AuditAction.CREATE)
    def post(self, request: Request, event_id: UUID) -> Response:
        """Assign (or re-role) a staff member by email."""
        from ctf.exceptions import CTFNotFoundError, CTFValidationError
        from ctf.services.event import assign_event_staff

        try:
            _resolve_owned_event(request, event_id)
            serializer = EventStaffAssignRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            try:
                staff = assign_event_staff(
                    event_id,
                    _actor(request),
                    serializer.validated_data["email"],
                    serializer.validated_data["role"],
                )
            except CTFNotFoundError as exc:
                _raise_not_found(str(exc))
            except CTFValidationError as exc:
                _raise_bad_request(str(exc))
            return Response(_staff_payload(staff), status=status.HTTP_201_CREATED)
        except _CtfApiError as exc:
            return exc.to_response(request)


class EventStaffMemberView(APIView):
    """Revoke (DELETE) one staff assignment on an owned event."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_write_scopes = _EVENT_WRITE

    @extend_schema(responses=ParticipantDeleteResultSerializer)
    @audit_admin_event_mutation("staff.revoke", action=AuditAction.DELETE)
    def delete(self, request: Request, event_id: UUID, user_id: int) -> Response:
        """Remove the assignment; the user keeps their platform account."""
        from ctf.exceptions import CTFNotFoundError, CTFValidationError
        from ctf.services.event import revoke_event_staff

        try:
            _resolve_owned_event(request, event_id)
            try:
                revoke_event_staff(event_id, _actor(request), user_id)
            except CTFNotFoundError as exc:
                _raise_not_found(str(exc))
            except CTFValidationError as exc:
                _raise_bad_request(str(exc))
            return Response({"deleted": True, "id": str(user_id)})
        except _CtfApiError as exc:
            return exc.to_response(request)


class EventOwnershipTransferView(APIView):
    """Transfer canonical ownership to a co-organizer (POST, owner-only, #1922)."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_write_scopes = _EVENT_WRITE

    @extend_schema(request=EventOwnershipTransferRequestSerializer, responses=EventMutationResultSerializer)
    def post(self, request: Request, event_id: UUID) -> Response:
        """Promote a current co-organizer to owner; the previous owner stays a co-organizer."""
        from ctf.exceptions import CTFNotFoundError, CTFValidationError
        from ctf.services.event import transfer_event_ownership

        try:
            # Owner-only topology op: the owner or the platform-admin override,
            # never delegated staff (ADR-052, #1922).
            _resolve_owned_event(request, event_id)
            serializer = EventOwnershipTransferRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            try:
                event = transfer_event_ownership(
                    event_id,
                    _actor(request),
                    serializer.validated_data["user_id"],
                )
            except CTFNotFoundError as exc:
                _raise_not_found(str(exc))
            except CTFValidationError as exc:
                _raise_bad_request(str(exc))
            return Response({"id": str(event.id), "name": event.name, "status": event.status})
        except _CtfApiError as exc:
            return exc.to_response(request)
