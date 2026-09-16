"""Organizer event views for the canonical CTF API (events + scenarios)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ctf.api._base import CTF_ORGANIZER_PERMISSIONS, _CtfApiError
from ctf.api.organizer._audit import (
    _audit_admin_mutation,
    admin_external_audit,
)
from ctf.api.organizer._base import (
    _EVENT_NOT_FOUND,
    _EVENT_READ,
    _EVENT_WRITE,
    _actor,
    _capture_event_authority,
    _event_authority,
    _raise_bad_request,
    _raise_forbidden,
    _raise_invalid_event,
    _raise_not_found,
    _resolve_owned_event,
)
from ctf.api.serializers import (
    CtfScenarioListResponseSerializer,
    EventDetailSerializer,
    EventListQuerySerializer,
    EventListResponseSerializer,
    EventMutationResultSerializer,
    EventSummarySerializer,
    EventWriteSerializer,
    ForceDeleteEventRequestSerializer,
    ForceDeleteEventResultSerializer,
)
from ctf.enums import EventCapability

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Any
    from uuid import UUID

    from django.contrib.auth.models import User
    from django.db.models import QuerySet

    from ctf.models import CTFEvent

# Canonical page-size bound for the authority-aware event list. The platform-admin
# path (all live events) is always bounded to this even when the caller omits
# pagination; an ordinary organizer keeps the historical full-list response
# (ADR-052-R3, ADR-040).
_EVENT_LIST_PAGE_SIZE = 200


def _bounded_event_page(
    events: QuerySet[CTFEvent], *, page: int | None, page_size: int | None, is_admin: bool
) -> QuerySet[CTFEvent]:
    """Slice the ordered queryset by explicit pagination, else bound the admin path."""
    if page is not None or page_size is not None:
        size = page_size or _EVENT_LIST_PAGE_SIZE
        start = ((page or 1) - 1) * size
        return events[start : start + size]
    if is_admin:
        return events[:_EVENT_LIST_PAGE_SIZE]
    return events


def _event_projection_context(
    request: Request, actor: User, events: Sequence[CTFEvent], *, is_admin: bool
) -> dict[str, Any]:
    """Build serializer context with a prefetched staff-role map (no per-row query)."""
    context: dict[str, Any] = {"request": request, "actor": actor, "is_platform_admin": is_admin, "staff_roles": {}}
    if not is_admin:
        event_ids = [event.id for event in events]
        if event_ids:
            from ctf.models import CTFEventStaff

            context["staff_roles"] = dict(
                CTFEventStaff.objects.filter(user=actor, event_id__in=event_ids, deleted_at__isnull=True).values_list(
                    "event_id", "role"
                )
            )
    return context


class EventListView(APIView):
    """List the organizer's events (GET) or create one (POST)."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_read_scopes = _EVENT_READ
    required_write_scopes = _EVENT_WRITE

    @extend_schema(
        operation_id="ctf_events_list",
        parameters=[EventListQuerySerializer],
        responses=EventListResponseSerializer,
    )
    def get(self, request: Request) -> Response:
        """Return the events the actor may administer (authority-aware, bounded).

        A platform administrator sees all live events; an ordinary organizer sees
        owned plus live staff-assigned events. Search/status/owner/ordering are
        allowlisted data filters; the admin path is bounded to the canonical page
        size. The v1 ``{"events": [...]}`` envelope is unchanged (ADR-040).
        """
        from ctf.services.authorization import is_ctf_platform_admin
        from ctf.services.event._queries import resolve_administrable_events

        actor = _actor(request)
        query = EventListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        params = query.validated_data

        events = resolve_administrable_events(actor, status=params.get("status") or None)
        search = params.get("search")
        if search:
            events = events.filter(name__icontains=search)
        owner = params.get("owner")
        if owner:
            try:
                events = events.filter(created_by_id=int(owner))
            except (TypeError, ValueError):
                events = events.none()
        ordering = params.get("ordering")
        if ordering:
            events = events.order_by(ordering, "id")

        is_admin = is_ctf_platform_admin(actor)
        page = _bounded_event_page(
            events, page=params.get("page"), page_size=params.get("page_size"), is_admin=is_admin
        )
        rows = list(page)
        context = _event_projection_context(request, actor, rows, is_admin=is_admin)
        return Response({"events": EventSummarySerializer(rows, many=True, context=context).data})

    @extend_schema(request=EventWriteSerializer, responses={201: EventMutationResultSerializer})
    def post(self, request: Request) -> Response:
        """Create an event from the request body.

        Creation is organizer authority, never the platform-admin override
        (ADR-052): a new event has no existing event on which to resolve override
        authority, and creation makes the actor ``created_by``. The list GET is
        admitted for organizers or platform admins, but POST requires a genuine
        CTF organizer, so a pure superuser cannot create an event and acquire
        ownership.
        """
        from django.core.exceptions import ValidationError

        from ctf.bridges import get_user_role
        from ctf.exceptions import CTFValidationError
        from ctf.services import create_event

        if not get_user_role(_actor(request)).is_ctf_organizer:
            try:
                _raise_forbidden()
            except _CtfApiError as exc:
                return exc.to_response(request)

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
        """Return the full event detail projection with owner and access context."""
        from ctf.services.authorization import is_ctf_platform_admin

        try:
            event = _resolve_owned_event(request, event_id, capability=EventCapability.CONFIG)
        except _CtfApiError as exc:
            return exc.to_response(request)
        actor = _actor(request)
        context = _event_projection_context(request, actor, [event], is_admin=is_ctf_platform_admin(actor))
        return Response(EventDetailSerializer(event, context=context).data)

    @extend_schema(request=EventWriteSerializer, responses=EventMutationResultSerializer)
    def put(self, request: Request, event_id: UUID) -> Response:
        """Update mutable fields of an owned event."""
        from django.core.exceptions import ValidationError
        from django.db import transaction

        from ctf.exceptions import CTFStateError, CTFValidationError
        from ctf.services import update_event

        try:
            event = _resolve_owned_event(request, event_id, capability=EventCapability.CONFIG)
            source = _event_authority(request, event, EventCapability.CONFIG)
            serializer = EventWriteSerializer(data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            changed = sorted(serializer.validated_data.keys())
            try:
                # Database-only mutation: the update and its platform-admin
                # override audit share one transaction, so a strict audit failure
                # rolls the update back (ADR-052-R4). The service asserts the
                # config capability again (defense in depth, #1922).
                with transaction.atomic():
                    updated = update_event(event_id, dict(serializer.validated_data), actor_id=_actor(request).pk)
                    _audit_admin_mutation(request, event, source, "event.update", changed_fields=changed)
            except (CTFValidationError, CTFStateError, ValidationError):
                _raise_invalid_event()
            return Response({"id": str(updated.id), "name": updated.name, "status": updated.status})
        except _CtfApiError as exc:
            return exc.to_response(request)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, event_id: UUID) -> Response:
        """Soft-delete an owned event."""
        from django.db import transaction

        from ctf.services import delete_event

        try:
            event = _resolve_owned_event(request, event_id, capability=EventCapability.DELETE)
            source = _event_authority(request, event, EventCapability.DELETE)
        except _CtfApiError as exc:
            return exc.to_response(request)
        from shared.audit import AuditAction

        with transaction.atomic():
            delete_event(event_id, actor_id=_actor(request).pk)
            _audit_admin_mutation(request, event, source, "event.delete", action=AuditAction.DELETE)
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
            # Owner, full co-organizer (delete capability), or the platform-admin
            # override may force-delete; the typed-name confirmation and lifecycle
            # safeguards below still apply unchanged (#1922, ADR-052-R5).
            source = _event_authority(request, event, EventCapability.DELETE)
            if source is None:
                _raise_forbidden()
            _capture_event_authority(request, event, source)
            confirmation_name = request.data.get("confirmation_name") if isinstance(request.data, dict) else None
            if not confirmation_name:
                _raise_bad_request("confirmation_name is required.")
            import ctf.services as ctf_services
            from shared.audit import AuditAction

            # Non-rollbackable range teardown: the context manager records bounded
            # override intent before the first side effect and a correlated
            # completed/failed outcome on EVERY exit path (ADR-052-R4).
            with admin_external_audit(request, "event.force_delete", action=AuditAction.DELETE):
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
