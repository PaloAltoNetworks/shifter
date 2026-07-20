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
from ctf.api.organizer._base import (
    _EVENT_READ,
    _EVENT_WRITE,
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
            _resolve_owned_event(request, event_id, capability="submissions")
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
        """Return the event's pages in display order."""
        from ctf.models import CTFEventPage

        try:
            _resolve_owned_event(request, event_id)
        except _CtfApiError as exc:
            return exc.to_response(request)
        pages = CTFEventPage.objects.filter(event_id=event_id, deleted_at__isnull=True)
        return Response({"pages": [_page_payload(p) for p in pages]})

    @extend_schema(request=EventPageWriteSerializer, responses=EventPageSerializer)
    def post(self, request: Request, event_id: UUID) -> Response:
        """Create a page; slugs are unique per event."""
        from django.core.exceptions import ValidationError
        from django.utils.text import slugify

        from ctf.models import CTFEventPage

        try:
            event = _resolve_owned_event(request, event_id)
            serializer = EventPageWriteSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            slug = slugify(data.get("slug") or data["title"])[:140]
            try:
                page = CTFEventPage.objects.create(
                    event=event,
                    title=data["title"],
                    slug=slug,
                    body=data["body"],
                    order=data.get("order", 0),
                )
            except ValidationError:
                _raise_bad_request("A page with this slug already exists")
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
        _resolve_owned_event(request, page.event_id)
        return page

    @extend_schema(request=EventPageWriteSerializer, responses=EventPageSerializer)
    def put(self, request: Request, page_id: UUID) -> Response:
        """Update the page's title, body, or order (the slug is stable)."""
        try:
            page = self._resolve(request, page_id)
            serializer = EventPageWriteSerializer(data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            for field in ("title", "body", "order"):
                if field in serializer.validated_data:
                    setattr(page, field, serializer.validated_data[field])
            page.save()
            return Response(_page_payload(page))
        except _CtfApiError as exc:
            return exc.to_response(request)

    @extend_schema(responses=ParticipantDeleteResultSerializer)
    def delete(self, request: Request, page_id: UUID) -> Response:
        """Soft-delete the page."""
        try:
            page = self._resolve(request, page_id)
            page.delete(soft=True)
            return Response({"deleted": True, "id": str(page_id)})
        except _CtfApiError as exc:
            return exc.to_response(request)
