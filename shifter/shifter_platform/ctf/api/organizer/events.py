"""Organizer event views for the canonical CTF API (events + scenarios)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ctf.api._base import CTF_ORGANIZER_PERMISSIONS, _CtfApiError
from ctf.api.organizer._base import (
    _EVENT_NOT_FOUND,
    _EVENT_READ,
    _EVENT_WRITE,
    _actor,
    _raise_bad_request,
    _raise_forbidden,
    _raise_invalid_event,
    _raise_not_found,
    _resolve_owned_event,
)
from ctf.api.serializers import (
    CtfScenarioListResponseSerializer,
    EventDetailSerializer,
    EventListResponseSerializer,
    EventMutationResultSerializer,
    EventSummarySerializer,
    EventWriteSerializer,
    ForceDeleteEventRequestSerializer,
    ForceDeleteEventResultSerializer,
)

if TYPE_CHECKING:
    from uuid import UUID


class EventListView(APIView):
    """List the organizer's events (GET) or create one (POST)."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_read_scopes = _EVENT_READ
    required_write_scopes = _EVENT_WRITE

    @extend_schema(operation_id="ctf_events_list", responses=EventListResponseSerializer)
    def get(self, request: Request) -> Response:
        """Return the organizer's events."""
        from ctf.services import get_organizer_events

        events = get_organizer_events(_actor(request))
        return Response({"events": EventSummarySerializer(events, many=True).data})

    @extend_schema(request=EventWriteSerializer, responses={201: EventMutationResultSerializer})
    def post(self, request: Request) -> Response:
        """Create an event from the request body."""
        from django.core.exceptions import ValidationError

        from ctf.exceptions import CTFValidationError
        from ctf.services import create_event

        serializer = EventWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            try:
                event = create_event(_actor(request), dict(serializer.validated_data))
            except (CTFValidationError, ValidationError):
                _raise_invalid_event()
            return Response(
                {"id": str(event.id), "name": event.name, "status": event.status},
                status=status.HTTP_201_CREATED,
            )
        except _CtfApiError as exc:
            return exc.to_response(request)


class EventDetailView(APIView):
    """Get, update, or delete a single owned event."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_read_scopes = _EVENT_READ
    required_write_scopes = _EVENT_WRITE

    @extend_schema(operation_id="ctf_events_retrieve", responses=EventDetailSerializer)
    def get(self, request: Request, event_id: UUID) -> Response:
        """Return the full event detail projection."""
        try:
            event = _resolve_owned_event(request, event_id)
        except _CtfApiError as exc:
            return exc.to_response(request)
        return Response(EventDetailSerializer(event).data)

    @extend_schema(request=EventWriteSerializer, responses=EventMutationResultSerializer)
    def put(self, request: Request, event_id: UUID) -> Response:
        """Update mutable fields of an owned event."""
        from django.core.exceptions import ValidationError

        from ctf.exceptions import CTFStateError, CTFValidationError
        from ctf.services import update_event

        try:
            _resolve_owned_event(request, event_id)
            serializer = EventWriteSerializer(data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            try:
                updated = update_event(event_id, dict(serializer.validated_data))
            except (CTFValidationError, CTFStateError, ValidationError):
                _raise_invalid_event()
            return Response({"id": str(updated.id), "name": updated.name, "status": updated.status})
        except _CtfApiError as exc:
            return exc.to_response(request)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, event_id: UUID) -> Response:
        """Soft-delete an owned event."""
        from ctf.services import delete_event

        try:
            _resolve_owned_event(request, event_id)
        except _CtfApiError as exc:
            return exc.to_response(request)
        delete_event(event_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ForceDeleteEventView(APIView):
    """Force-delete an event and tear down its ranges."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_write_scopes = _EVENT_WRITE

    @extend_schema(request=ForceDeleteEventRequestSerializer, responses=ForceDeleteEventResultSerializer)
    def post(self, request: Request, event_id: UUID) -> Response:
        """Validate the confirmation name and force-delete the event."""
        from ctf.exceptions import CTFValidationError
        from ctf.models import CTFEvent

        try:
            try:
                event = CTFEvent.all_objects.get(pk=event_id)
            except CTFEvent.DoesNotExist:
                _raise_not_found(_EVENT_NOT_FOUND)
            if event.created_by_id != _actor(request).pk:
                _raise_forbidden()
            confirmation_name = request.data.get("confirmation_name") if isinstance(request.data, dict) else None
            if not confirmation_name:
                _raise_bad_request("confirmation_name is required.")
            import ctf.services as ctf_services

            try:
                result = ctf_services.force_delete_event(event_id, _actor(request), confirmation_name)
            except CTFValidationError:
                _raise_invalid_event()
            return Response(result)
        except _CtfApiError as exc:
            return exc.to_response(request)


class ScenarioListView(APIView):
    """List CMS scenarios available for CTF events."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_read_scopes = _EVENT_READ

    @extend_schema(responses=CtfScenarioListResponseSerializer)
    def get(self, request: Request) -> Response:
        """Return scenario id/name pairs from the CMS registry."""
        import ctf.bridges as ctf_bridges

        scenarios = [{"id": sid, "name": name} for sid, name in ctf_bridges.cms_list_scenarios(_actor(request))]
        return Response({"scenarios": scenarios})
