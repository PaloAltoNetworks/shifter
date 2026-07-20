"""Organizer import/export and webhook views (CTF-1101..1104, CTF-1203)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.http import HttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ctf.api._base import CTF_ORGANIZER_PERMISSIONS, _CtfApiError
from ctf.api.organizer._base import (
    _EVENT_READ,
    _EVENT_WRITE,
    _actor,
    _raise_bad_request,
    _raise_not_found,
    _resolve_owned_event,
)
from ctf.api.serializers import (
    ChallengeImportRequestSerializer,
    ChallengeImportResultSerializer,
    ParticipantDeleteResultSerializer,
    WebhookListResponseSerializer,
    WebhookSerializer,
    WebhookWriteSerializer,
)

if TYPE_CHECKING:
    from uuid import UUID

    from ctf.models import CTFWebhook

logger = logging.getLogger(__name__)


class ChallengeExportView(APIView):
    """Export an owned event's challenges (GET, CTF-1102/CTF-1104)."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_read_scopes = _EVENT_READ

    @extend_schema(responses={200: dict})
    def get(self, request: Request, event_id: UUID) -> Response:
        """Return the export document; ``?fmt=ctfd`` selects CTFd shape."""
        from ctf.services.transfer import export_challenges

        try:
            _resolve_owned_event(request, event_id)
            fmt = request.query_params.get("fmt", "shifter")
            if fmt not in {"shifter", "ctfd"}:
                _raise_bad_request("Unknown export format")
            return Response(export_challenges(event_id, fmt=fmt))
        except _CtfApiError as exc:
            return exc.to_response(request)


class ChallengeImportView(APIView):
    """Import challenges into an owned event (POST, CTF-1101/CTF-1104)."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_write_scopes = _EVENT_WRITE

    @extend_schema(request=ChallengeImportRequestSerializer, responses=ChallengeImportResultSerializer)
    def post(self, request: Request, event_id: UUID) -> Response:
        """Run a partial-success import of the posted document."""
        from ctf.exceptions import CTFValidationError
        from ctf.services.transfer import import_challenges

        try:
            _resolve_owned_event(request, event_id)
            serializer = ChallengeImportRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            try:
                result = import_challenges(event_id, serializer.validated_data["payload"], actor_id=_actor(request).pk)
            except CTFValidationError:
                _raise_bad_request("Import payload has no challenges list.")
            return Response(result)
        except _CtfApiError as exc:
            return exc.to_response(request)


class EventResultsExportView(APIView):
    """Export event results and statistics (GET, CTF-1103)."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_read_scopes = _EVENT_READ

    @extend_schema(responses={200: dict})
    def get(self, request: Request, event_id: UUID) -> Response | HttpResponse:
        """Return results as JSON, or CSV with ``?fmt=csv``."""
        from ctf.services.transfer import export_event_results, results_csv

        try:
            _resolve_owned_event(request, event_id)
        except _CtfApiError as exc:
            return exc.to_response(request)
        results = export_event_results(event_id)
        if request.query_params.get("fmt") == "csv":
            response = HttpResponse(results_csv(results), content_type="text/csv")
            response["Content-Disposition"] = 'attachment; filename="event-results.csv"'
            return response
        return Response(results)


def _webhook_payload(webhook: CTFWebhook) -> dict[str, object]:
    """Render one webhook row (the secret is write-only)."""
    return {
        "id": str(webhook.id),
        "url": webhook.url,
        "subscribed_events": webhook.subscribed_events,
        "active": webhook.active,
        "has_secret": bool(webhook.secret),
        "last_status": webhook.last_status,
        "last_delivery_at": webhook.last_delivery_at,
    }


class EventWebhooksView(APIView):
    """List (GET) or register (POST) webhooks on an owned event (CTF-1203)."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_read_scopes = _EVENT_READ
    required_write_scopes = _EVENT_WRITE

    @extend_schema(responses=WebhookListResponseSerializer)
    def get(self, request: Request, event_id: UUID) -> Response:
        """Return the event's webhooks."""
        from ctf.models import CTFWebhook

        try:
            _resolve_owned_event(request, event_id)
        except _CtfApiError as exc:
            return exc.to_response(request)
        hooks = CTFWebhook.objects.filter(event_id=event_id, deleted_at__isnull=True).order_by("created_at")
        return Response({"webhooks": [_webhook_payload(h) for h in hooks]})

    @extend_schema(request=WebhookWriteSerializer, responses=WebhookSerializer)
    def post(self, request: Request, event_id: UUID) -> Response:
        """Register a webhook endpoint."""
        from ctf.models import CTFWebhook
        from ctf.services.webhook import WEBHOOK_EVENT_TYPES

        try:
            event = _resolve_owned_event(request, event_id)
            serializer = WebhookWriteSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            subscribed = serializer.validated_data.get("subscribed_events", [])
            unknown = [e for e in subscribed if e not in WEBHOOK_EVENT_TYPES]
            if unknown:
                _raise_bad_request(f"Unknown webhook event types: {', '.join(sorted(unknown))}")
            webhook = CTFWebhook.objects.create(
                event=event,
                url=serializer.validated_data["url"],
                secret=serializer.validated_data.get("secret", ""),
                subscribed_events=subscribed,
            )
            return Response(_webhook_payload(webhook), status=status.HTTP_201_CREATED)
        except _CtfApiError as exc:
            return exc.to_response(request)


class WebhookDetailView(APIView):
    """Remove (DELETE) one webhook (CTF-1203)."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_write_scopes = _EVENT_WRITE

    @extend_schema(responses=ParticipantDeleteResultSerializer)
    def delete(self, request: Request, webhook_id: UUID) -> Response:
        """Soft-delete the webhook after ownership checks."""
        from ctf.models import CTFWebhook

        try:
            webhook = CTFWebhook.objects.select_related("event").filter(pk=webhook_id, deleted_at__isnull=True).first()
            if webhook is None:
                _raise_not_found("Webhook not found")
            _resolve_owned_event(request, webhook.event_id)
            webhook.delete(soft=True)
            return Response({"deleted": True, "id": str(webhook_id)})
        except _CtfApiError as exc:
            return exc.to_response(request)
