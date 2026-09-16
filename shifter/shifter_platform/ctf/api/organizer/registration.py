"""Organizer review surface for public CTF registration requests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ctf.api._base import CTF_ORGANIZER_PERMISSIONS, _CtfApiError
from ctf.api.organizer._audit import _audit_admin_from_request, admin_external_audit
from ctf.api.organizer._base import (
    _EVENT_READ,
    _EVENT_WRITE,
    _actor,
    _pagination_window,
    _raise_bad_request,
    _raise_conflict,
    _raise_not_found,
    _resolve_owned_event,
)
from ctf.api.serializers import (
    PublicRegistrationDispositionResultSerializer,
    PublicRegistrationDispositionSerializer,
    PublicRegistrationRequestListResponseSerializer,
    PublicRegistrationRequestSerializer,
)
from shared.audit import AuditAction

if TYPE_CHECKING:
    from uuid import UUID

_REQUEST_NOT_FOUND = "Registration request not found"
_INVALID_DISPOSITION = "Invalid registration request action."
_ALREADY_DISPOSITIONED = "Registration request has already been reviewed."


class PublicRegistrationRequestListView(APIView):
    """List an event's pending public registration requests."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_read_scopes = _EVENT_READ

    @extend_schema(responses=PublicRegistrationRequestListResponseSerializer)
    def get(self, request: Request, event_id: UUID) -> Response:
        """Return the bounded pending queue for one authorized event."""
        from ctf.services.public_registration import list_pending_public_registration_requests

        try:
            _resolve_owned_event(request, event_id, capability="participants")
            requests = list_pending_public_registration_requests(event_id, actor_id=_actor(request).pk)
            total = requests.count()
            offset, limit = _pagination_window(request)
            limit = limit or 100
            requests = requests[offset : offset + limit]
            return Response(
                {
                    "requests": PublicRegistrationRequestSerializer(requests, many=True).data,
                    "total": total,
                }
            )
        except _CtfApiError as exc:
            return exc.to_response(request)


class PublicRegistrationDispositionView(APIView):
    """Approve or reject one still-pending public registration request."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_write_scopes = _EVENT_WRITE

    @staticmethod
    def _resolve_event_id(request_id: UUID) -> UUID:
        from ctf.models import CTFPublicRegistrationRequest

        event_id = CTFPublicRegistrationRequest.objects.filter(pk=request_id).values_list("event_id", flat=True).first()
        if event_id is None:
            _raise_not_found(_REQUEST_NOT_FOUND)
        return event_id

    @extend_schema(
        request=PublicRegistrationDispositionSerializer,
        responses=PublicRegistrationDispositionResultSerializer,
    )
    def post(self, request: Request, request_id: UUID) -> Response:
        """Validate authority and apply exactly one terminal disposition."""
        from ctf.exceptions import CTFValidationError
        from ctf.services.public_registration import (
            PublicRegistrationAlreadyDispositioned,
            PublicRegistrationRequestNotFound,
            approve_public_registration_request,
            reject_public_registration_request,
        )

        try:
            event_id = self._resolve_event_id(request_id)
            _resolve_owned_event(request, event_id, capability="participants")
            serializer = PublicRegistrationDispositionSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            action = serializer.validated_data["action"]
            if action not in {"approve", "reject"}:
                _raise_bad_request(_INVALID_DISPOSITION)
            try:
                if action == "approve":
                    with admin_external_audit(
                        request,
                        "public_registration.approve",
                        action=AuditAction.CREATE,
                    ):
                        result = approve_public_registration_request(
                            request_id,
                            actor_id=_actor(request).pk,
                        )
                else:
                    with transaction.atomic():
                        result = reject_public_registration_request(
                            request_id,
                            actor_id=_actor(request).pk,
                        )
                        _audit_admin_from_request(
                            request,
                            "public_registration.reject",
                            action=AuditAction.UPDATE,
                        )
            except PublicRegistrationRequestNotFound:
                _raise_not_found(_REQUEST_NOT_FOUND)
            except PublicRegistrationAlreadyDispositioned:
                _raise_conflict(_ALREADY_DISPOSITIONED)
            except CTFValidationError:
                _raise_bad_request(_INVALID_DISPOSITION)
            return Response(PublicRegistrationDispositionResultSerializer(result).data)
        except _CtfApiError as exc:
            return exc.to_response(request)
