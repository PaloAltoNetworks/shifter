"""Organizer participant-management views for the canonical CTF API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ctf.api._base import CTF_ORGANIZER_PERMISSIONS, _CtfApiError
from ctf.api.organizer._audit import (
    admin_external_audit,
    audit_admin_event_mutation,
)
from ctf.api.organizer._base import (
    _BRACKET_NOT_FOUND,
    _EVENT_READ,
    _EVENT_WRITE,
    _INVALID_PARTICIPANT_REQUEST,
    _PARTICIPANT_NOT_FOUND,
    _actor,
    _pagination_window,
    _participant_detail_payload,
    _raise_bad_request,
    _raise_forbidden,
    _raise_not_found,
    _raise_throttled,
    _resolve_owned_event,
    _resolve_owned_participant,
)
from ctf.api.serializers import (
    AssignBracketRequestSerializer,
    AssignBracketResultSerializer,
    ParticipantAddResultSerializer,
    ParticipantAddSerializer,
    ParticipantDeleteResultSerializer,
    ParticipantDetailSerializer,
    ParticipantImportResultSerializer,
    ParticipantImportSerializer,
    ParticipantListResponseSerializer,
    ParticipantPasswordRequestSerializer,
    ParticipantPasswordResultSerializer,
    ResendLoginInfoResultSerializer,
)
from shared.audit import AuditAction
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger(__name__)


class ParticipantListView(APIView):
    """List an event's participants (GET) or invite one (POST)."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_read_scopes = _EVENT_READ
    required_write_scopes = _EVENT_WRITE

    @extend_schema(responses=ParticipantListResponseSerializer)
    def get(self, request: Request, event_id: UUID) -> Response:
        """Return the participants of an owned event, optionally filtered by status."""
        from ctf.services import list_participants_for_event

        try:
            _resolve_owned_event(request, event_id, capability="participants")
        except _CtfApiError as exc:
            return exc.to_response(request)
        participants = list_participants_for_event(event_id)
        status_filter = request.query_params.get("status")
        if status_filter:
            participants = participants.filter(status=status_filter)
        total = participants.count()
        offset, limit = _pagination_window(request)
        if limit is not None:
            participants = participants[offset : offset + limit]
        data = [
            {
                "id": str(p.id),
                "name": p.name,
                "email": p.email,
                "status": p.status,
                "role": p.role,
                "hidden": p.hidden,
                "team_name": p.team.name if p.team else None,
                "registered_at": p.registered_at.isoformat() if p.registered_at else None,
                "total_score": p.total_score,
            }
            for p in participants
        ]
        return Response({"participants": data, "total": total})

    @extend_schema(request=ParticipantAddSerializer, responses={201: ParticipantAddResultSerializer})
    def post(self, request: Request, event_id: UUID) -> Response:
        """Invite a single participant to an owned event."""
        from ctf.exceptions import CTFValidationError
        from ctf.services import add_participant

        try:
            _resolve_owned_event(request, event_id, capability="participants")
            serializer = ParticipantAddSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            name = serializer.validated_data["name"]
            email = serializer.validated_data["email"]
            try:
                # Non-rollbackable invite (may trigger provisioning): intent then outcome.
                with admin_external_audit(request, "participant.add", action=AuditAction.CREATE):
                    participant = add_participant(event_id, email, name)
            except CTFValidationError:
                _raise_bad_request(_INVALID_PARTICIPANT_REQUEST)
            return Response(
                {
                    "id": str(participant.id),
                    "name": participant.name,
                    "email": participant.email,
                    "status": participant.status,
                },
                status=status.HTTP_201_CREATED,
            )
        except _CtfApiError as exc:
            return exc.to_response(request)


class ParticipantImportView(APIView):
    """Bulk-import participants into an owned event (POST)."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_write_scopes = _EVENT_WRITE

    @extend_schema(request=ParticipantImportSerializer, responses=ParticipantImportResultSerializer)
    def post(self, request: Request, event_id: UUID) -> Response:
        """Validate the import body and invite each row, collecting per-row errors."""
        try:
            _resolve_owned_event(request, event_id, capability="participants")
        except _CtfApiError as exc:
            return exc.to_response(request)
        serializer = ParticipantImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with admin_external_audit(request, "participant.import", action=AuditAction.CREATE):
            return self._import(event_id, serializer.validated_data["participants"])

    @staticmethod
    def _import(event_id: UUID, participants_data: list[object]) -> Response:
        """Invite each row, mirroring the legacy per-item validation and error shapes."""
        from ctf.exceptions import CTFValidationError
        from ctf.services import add_participant

        imported: list[dict[str, str]] = []
        errors: list[dict[str, object]] = []
        for idx, p_data in enumerate(participants_data):
            # Each element must be an object; a bare scalar passed the list guard
            # but would raise AttributeError on .get() and surface as a 500
            # (#1149). Report it per-item instead.
            if not isinstance(p_data, dict):
                errors.append({"index": idx, "error": "each participant must be an object"})
                continue
            name = p_data.get("name")
            email = p_data.get("email")
            if not name or not email:
                errors.append({"index": idx, "error": "name and email are required"})
                continue
            try:
                participant = add_participant(event_id, email, name)
                imported.append(
                    {
                        "id": str(participant.id),
                        "name": participant.name,
                        "email": participant.email,
                    }
                )
            except CTFValidationError as exc:
                logger.warning("CTF participant import row %s failed: %s", idx, safe_log_value(str(exc)))
                errors.append({"index": idx, "email": email, "error": "Could not import participant."})
        return Response({"imported": len(imported), "participants": imported, "errors": errors})


class ParticipantDetailView(APIView):
    """Get (GET) or soft-delete (DELETE) a single owned participant."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_read_scopes = _EVENT_READ
    required_write_scopes = _EVENT_WRITE

    @extend_schema(responses=ParticipantDetailSerializer)
    def get(self, request: Request, participant_id: UUID) -> Response:
        """Return the full organizer participant detail projection."""
        try:
            participant = _resolve_owned_participant(
                request, participant_id, capability=("participants", "submissions")
            )
        except _CtfApiError as exc:
            return exc.to_response(request)
        return Response(_participant_detail_payload(participant))

    @extend_schema(responses=ParticipantDeleteResultSerializer)
    def delete(self, request: Request, participant_id: UUID) -> Response:
        """Soft-delete an owned participant."""
        from ctf.exceptions import CTFNotFoundError
        from ctf.services import delete_participant

        try:
            _resolve_owned_participant(request, participant_id, capability="participants")
            try:
                # Non-rollbackable delete (range teardown): intent then outcome.
                with admin_external_audit(request, "participant.delete", action=AuditAction.DELETE):
                    delete_participant(participant_id)
            except CTFNotFoundError:
                _raise_not_found(_PARTICIPANT_NOT_FOUND)
            return Response({"deleted": True, "id": str(participant_id)})
        except _CtfApiError as exc:
            return exc.to_response(request)


class ParticipantResendLoginInfoView(APIView):
    """Deprecated invitation-information resend (POST, no credential mutation)."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_write_scopes = _EVENT_WRITE

    @extend_schema(request=None, responses=ResendLoginInfoResultSerializer, deprecated=True)
    def post(self, request: Request, participant_id: UUID) -> Response:
        """Rate-limit, enforce ownership, then resend non-secret login information."""
        from ctf.exceptions import CTFStateError, CTFValidationError
        from ctf.services import resend_login_info
        from ctf.views._access import _check_credential_delivery_rate_limit

        try:
            if not _check_credential_delivery_rate_limit(_actor(request).pk):
                _raise_throttled("Too many invitations. Try again later.")
            _resolve_owned_participant(request, participant_id, capability="participants")
            try:
                with admin_external_audit(request, "participant.resend_login"):
                    updated = resend_login_info(participant_id)
            except (CTFStateError, CTFValidationError):
                # CTFValidationError covers the fail-closed bootstrap-credential path
                # (issue #1665): an unavailable/invalid configured source must surface
                # as a controlled 400, never an uncaught 500.
                _raise_bad_request(_INVALID_PARTICIPANT_REQUEST)
            return Response({"success": True, "id": str(updated.id)})
        except _CtfApiError as exc:
            return exc.to_response(request)


@method_decorator(sensitive_post_parameters("password"), name="dispatch")
class ParticipantPasswordView(APIView):
    """Issue one generated or organizer-supplied participant password."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_write_scopes = _EVENT_WRITE

    @extend_schema(
        request=ParticipantPasswordRequestSerializer,
        responses={200: ParticipantPasswordResultSerializer},
    )
    def post(self, request: Request, participant_id: UUID) -> Response:
        """Authorize, rate-limit, issue, and return the password once."""
        from ctf.exceptions import CTFNotFoundError, CTFValidationError
        from ctf.services import reset_participant_password
        from ctf.views._access import _check_credential_delivery_rate_limit
        from shared.audit import RequestAudit, get_client_ip, get_request_id

        try:
            _resolve_owned_participant(request, participant_id, capability="participants")
            try:
                allowed = _check_credential_delivery_rate_limit(_actor(request).pk)
            except Exception as exc:
                raise _CtfApiError(
                    code="service_unavailable",
                    message="Credential service is temporarily unavailable.",
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                ) from exc
            if not allowed:
                _raise_throttled("Too many credential operations. Try again later.")
            serializer = ParticipantPasswordRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            try:
                # Non-rollbackable credential issuance/delivery: intent then outcome.
                with admin_external_audit(request, "participant.password_reset"):
                    issuance = reset_participant_password(
                        participant_id,
                        actor=_actor(request),
                        kind=serializer.validated_data["kind"],
                        password=serializer.validated_data.get("password"),
                        request_audit=RequestAudit(
                            source_ip=get_client_ip(request),
                            user_agent=request.META.get("HTTP_USER_AGENT", "")[:512],
                            request_id=get_request_id(request),
                        ),
                    )
            except CTFNotFoundError:
                _raise_not_found(_PARTICIPANT_NOT_FOUND)
            except CTFValidationError as exc:
                if exc.code == "CTF_PERMISSION_DENIED":
                    _raise_forbidden()
                _raise_bad_request(_INVALID_PARTICIPANT_REQUEST)
            response = Response(
                {
                    "participant_id": str(issuance.participant_id),
                    "event_id": str(issuance.event_id),
                    "username": issuance.username,
                    "password": issuance.password,
                    "kind": issuance.kind,
                }
            )
            response["Cache-Control"] = "private, no-store"
            response["Pragma"] = "no-cache"
            response["Vary"] = "Cookie, Authorization"
            return response
        except _CtfApiError as exc:
            return exc.to_response(request)


class AssignBracketView(APIView):
    """Assign or remove a participant's bracket (POST)."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_write_scopes = _EVENT_WRITE

    @extend_schema(request=AssignBracketRequestSerializer, responses=AssignBracketResultSerializer)
    @audit_admin_event_mutation("participant.assign_bracket")
    def post(self, request: Request, participant_id: UUID) -> Response:
        """Enforce ownership, then assign (bracket_id given) or remove (null) the bracket."""
        try:
            _resolve_owned_participant(request, participant_id, capability="participants")
            serializer = AssignBracketRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            return self._set_bracket(participant_id, serializer.validated_data.get("bracket_id"))
        except _CtfApiError as exc:
            return exc.to_response(request)

    @staticmethod
    def _set_bracket(participant_id: UUID, bracket_id: object) -> Response:
        """Assign (bracket_id given) or remove (bracket_id None) a participant's bracket."""
        if bracket_id is None:
            from ctf.services.bracket import remove_participant_bracket

            remove_participant_bracket(participant_id)
            return Response({"status": "ok", "bracket": None})

        from uuid import UUID as _UUID

        from django.core.exceptions import ValidationError

        from ctf.models import CTFBracket
        from ctf.services.bracket import assign_participant_bracket

        try:
            bracket_uuid = _UUID(str(bracket_id))
            participant = assign_participant_bracket(participant_id, bracket_uuid)
        except ValueError:
            _raise_bad_request("Invalid bracket ID format")
        except ValidationError:
            _raise_bad_request("Bracket and participant must belong to the same event")
        except CTFBracket.DoesNotExist:
            _raise_not_found(_BRACKET_NOT_FOUND)
        bracket = participant.bracket
        return Response(
            {
                "status": "ok",
                "bracket": {"id": str(bracket.id), "name": bracket.name} if bracket else None,
            }
        )
