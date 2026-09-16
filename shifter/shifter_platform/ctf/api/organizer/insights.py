"""Organizer analytics and custom-page views (CTF-1302, CTF-1303)."""

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
    EventPageSerializer,
    EventPagesResponseSerializer,
    EventPageWriteSerializer,
    ParticipantDeleteResultSerializer,
)
from ctf.enums import EventCapability
from shared.audit import AuditAction

if TYPE_CHECKING:
    from uuid import UUID

    from ctf.models import CTFEventPage

logger = logging.getLogger(__name__)


class EventAnalyticsView(APIView):
    """Event performance analytics (GET, CTF-1302)."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_read_scopes = _EVENT_READ

    @extend_schema(responses={200: dict})
    def get(self, request: Request, event_id: UUID) -> Response:
        """Return score distribution, solve timeline, challenge and engagement stats."""
        from ctf.services.scoring import get_event_analytics

        try:
            _resolve_owned_event(request, event_id, capability=EventCapability.SUBMISSIONS)
        except _CtfApiError as exc:
            return exc.to_response(request)
        return Response(get_event_analytics(event_id))


def _page_payload(page: CTFEventPage) -> dict[str, object]:
    """Render one custom page."""
    return {
        "id": str(page.id),
        "title": page.title,
        "slug": page.slug,
        "body": page.body,
        "order": page.order,
    }


class EventPagesView(APIView):
    """List (GET) or create (POST) an event's custom pages (CTF-1303)."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_read_scopes = _EVENT_READ
    required_write_scopes = _EVENT_WRITE

    @extend_schema(responses=EventPagesResponseSerializer)
    def get(self, request: Request, event_id: UUID) -> Response:
        """Return the event's pages in display order (incl. the reserved briefing).

        The organizer editor sees every page and separates the reserved briefing
        into its own affordance; participant reads exclude it (#1854).
        """
        from ctf.services.event.pages import list_active_pages

        try:
            _resolve_owned_event(request, event_id, capability=EventCapability.CONTENT)
        except _CtfApiError as exc:
            return exc.to_response(request)
        pages = list_active_pages(event_id, include_reserved=True)
        return Response({"pages": [_page_payload(p) for p in pages]})

    @extend_schema(request=EventPageWriteSerializer, responses=EventPageSerializer)
    @audit_admin_event_mutation("event_page.create", action=AuditAction.CREATE)
    def post(self, request: Request, event_id: UUID) -> Response:
        """Create a page through the CTF page service; slugs are unique per event."""
        from ctf.exceptions import CTFValidationError
        from ctf.services.event.pages import create_event_page

        try:
            event = _resolve_owned_event(request, event_id, capability=EventCapability.CONTENT)
            serializer = EventPageWriteSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            try:
                page = create_event_page(
                    event,
                    title=data["title"],
                    body=data["body"],
                    slug=data.get("slug"),
                    order=data.get("order", 0),
                    actor_id=_actor(request).pk,
                )
            except CTFValidationError as exc:
                _raise_bad_request(str(exc))
            return Response(_page_payload(page), status=status.HTTP_201_CREATED)
        except _CtfApiError as exc:
            return exc.to_response(request)


class EventPageDetailView(APIView):
    """Update (PUT) or remove (DELETE) one custom page (CTF-1303)."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_write_scopes = _EVENT_WRITE

    def _resolve(self, request: Request, page_id: UUID) -> CTFEventPage:
        from ctf.models import CTFEventPage

        page = CTFEventPage.objects.select_related("event").filter(pk=page_id, deleted_at__isnull=True).first()
        if page is None:
            _raise_not_found("Page not found")
        _resolve_owned_event(request, page.event_id, capability=EventCapability.CONTENT)
        return page

    @extend_schema(request=EventPageWriteSerializer, responses=EventPageSerializer)
    @audit_admin_event_mutation("event_page.update")
    def put(self, request: Request, page_id: UUID) -> Response:
        """Update the page's title, body, or order (the slug is stable)."""
        from ctf.exceptions import CTFValidationError
        from ctf.services.event.pages import update_event_page

        try:
            page = self._resolve(request, page_id)
            serializer = EventPageWriteSerializer(data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            try:
                update_event_page(page, fields=serializer.validated_data, actor_id=_actor(request).pk)
            except CTFValidationError as exc:
                _raise_bad_request(str(exc))
            return Response(_page_payload(page))
        except _CtfApiError as exc:
            return exc.to_response(request)

    @extend_schema(responses=ParticipantDeleteResultSerializer)
    @audit_admin_event_mutation("event_page.delete", action=AuditAction.DELETE)
    def delete(self, request: Request, page_id: UUID) -> Response:
        """Soft-delete the page."""
        from ctf.services.event.pages import delete_event_page

        try:
            page = self._resolve(request, page_id)
            delete_event_page(page, actor_id=_actor(request).pk)
            return Response({"deleted": True, "id": str(page_id)})
        except _CtfApiError as exc:
            return exc.to_response(request)
