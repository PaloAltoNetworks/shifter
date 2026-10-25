"""Organizer notification views for the canonical CTF API.

Announcements, notification dispatch, per-event email-template overrides, and the
send-invitations action.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from drf_spectacular.utils import extend_schema
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
    _pagination_window,
    _raise_bad_request,
    _raise_not_found,
    _resolve_owned_event,
)
from ctf.api.serializers import (
    EmailTemplateResponseSerializer,
    EmailTemplateRevertResultSerializer,
    EmailTemplateWriteSerializer,
    NotificationListResponseSerializer,
)
from shared.audit import AuditAction

if TYPE_CHECKING:
    from uuid import UUID

    from ctf.models import CTFEmailTemplate, CTFEvent

logger = logging.getLogger(__name__)


def _email_template_payload(template: CTFEmailTemplate) -> dict[str, object]:
    """Render the per-event email-template JSON payload.

    Mirrors ``ctf.views.api.notifications._handle_get_email_template`` /
    ``_handle_put_email_template`` key-for-key.
    """
    return {
        "id": str(template.id),
        "notification_type": template.notification_type,
        "subject": template.subject,
        "html_body": template.html_body,
        "text_body": template.text_body,
    }


def _validate_email_template_bodies(html_body: str, text_body: str, notification_type: str) -> None:
    """Validate the two organizer email-template bodies, raising a 400 on any violation.

    Mirrors ``ctf.views.api.notifications._validate_template_bodies``: request
    input is never compiled into a Django ``Template``; only the flat
    ``{{ name }}`` placeholder grammar over the per-type scalar allowlist is
    permitted (CWE-1336, issue #1095).
    """
    from ctf.services.email_template import allowed_placeholders, find_template_violations

    allowed = allowed_placeholders(notification_type)
    for label, source in (("html_body", html_body), ("text_body", text_body)):
        if not source:
            _raise_bad_request("html_body and text_body are required")
        violations = find_template_violations(source, allowed)
        if violations:
            _raise_bad_request(f"Invalid template syntax in {label}: {violations[0]}")


class SendLoginInfoView(APIView):
    """Send invitation emails to all uninvited participants of an owned event."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_write_scopes = _EVENT_WRITE

    @extend_schema(exclude=True)
    def post(self, request: Request, **kwargs: Any) -> Response:
        from ctf.api.retired_notifications import retired_notification_response

        return retired_notification_response(request)


class NotificationListView(APIView):
    """List an event's notifications (GET) or send an announcement (POST)."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_read_scopes = _EVENT_READ
    required_write_scopes = _EVENT_WRITE

    @extend_schema(responses=NotificationListResponseSerializer)
    def get(self, request: Request, event_id: UUID) -> Response:
        """Return the notifications for an owned event, newest first."""
        from ctf.models import CTFNotification

        try:
            event = _resolve_owned_event(request, event_id, capability="notifications")
        except _CtfApiError as exc:
            return exc.to_response(request)
        queryset = CTFNotification.objects.filter(event=event).order_by("-created_at")
        total = queryset.count()
        offset, limit = _pagination_window(request)
        notifications = queryset[offset : offset + limit] if limit is not None else queryset
        data = [
            {
                "id": str(n.id),
                "notification_type": n.notification_type,
                "subject": n.subject,
                "status": n.status,
                "sent_count": n.sent_count,
                "created_at": n.created_at.isoformat(),
                "sent_at": n.sent_at.isoformat() if n.sent_at else None,
                "scheduled_at": n.scheduled_at.isoformat() if n.scheduled_at else None,
            }
            for n in notifications
        ]
        return Response({"notifications": data, "total": total})

    @extend_schema(exclude=True)
    def post(self, request: Request, **kwargs: Any) -> Response:
        from ctf.api.retired_notifications import retired_notification_response

        return retired_notification_response(request)


class NotificationCancelScheduleView(APIView):
    """Cancel a scheduled notification before delivery (POST, CTF-804)."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_write_scopes = _EVENT_WRITE

    @extend_schema(exclude=True)
    def post(self, request: Request, **kwargs: Any) -> Response:
        from ctf.api.retired_notifications import retired_notification_response

        return retired_notification_response(request)


class NotificationSendView(APIView):
    """Dispatch a notification to its recipients (organizer)."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_write_scopes = _EVENT_WRITE

    @extend_schema(exclude=True)
    def post(self, request: Request, **kwargs: Any) -> Response:
        from ctf.api.retired_notifications import retired_notification_response

        return retired_notification_response(request)


class EventEmailTemplateView(APIView):
    """Get, create/update, or revert a per-event email-template override."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_read_scopes = _EVENT_READ
    required_write_scopes = _EVENT_WRITE

    def _resolve(self, request: Request, event_id: UUID, notification_type: str) -> CTFEvent:
        """Validate the notification type (400) then resolve and own the event (404/403)."""
        from ctf.enums import NotificationType

        valid_types = {nt.value for nt in NotificationType}
        if notification_type not in valid_types:
            _raise_bad_request(f"Invalid notification type: {notification_type}")
        return _resolve_owned_event(request, event_id, capability="notifications")

    @extend_schema(responses=EmailTemplateResponseSerializer)
    def get(self, request: Request, event_id: UUID, notification_type: str) -> Response:
        """Return the per-event custom template, or 404 when using the default."""
        from ctf.models import CTFEmailTemplate

        try:
            event = self._resolve(request, event_id, notification_type)
            template = CTFEmailTemplate.objects.filter(event=event, notification_type=notification_type).first()
            if template is None:
                _raise_not_found("No custom template")
            return Response(_email_template_payload(template))
        except _CtfApiError as exc:
            return exc.to_response(request)

    @extend_schema(request=EmailTemplateWriteSerializer, responses=EmailTemplateResponseSerializer)
    @audit_admin_event_mutation("email_template.update")
    def put(self, request: Request, event_id: UUID, notification_type: str) -> Response:
        """Create or update the per-event custom template from the request body."""
        from ctf.models import CTFEmailTemplate

        try:
            event = self._resolve(request, event_id, notification_type)
            serializer = EmailTemplateWriteSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            html_body = serializer.validated_data["html_body"].strip()
            text_body = serializer.validated_data["text_body"].strip()
            subject = serializer.validated_data["subject"].strip()
            _validate_email_template_bodies(html_body, text_body, notification_type)
            template, _created = CTFEmailTemplate.objects.update_or_create(
                event=event,
                notification_type=notification_type,
                defaults={"subject": subject, "html_body": html_body, "text_body": text_body},
            )
            return Response(_email_template_payload(template))
        except _CtfApiError as exc:
            return exc.to_response(request)

    @extend_schema(responses=EmailTemplateRevertResultSerializer)
    @audit_admin_event_mutation("email_template.revert", action=AuditAction.DELETE)
    def delete(self, request: Request, event_id: UUID, notification_type: str) -> Response:
        """Soft-delete the per-event template, reverting to the platform default."""
        from ctf.models import CTFEmailTemplate

        try:
            event = self._resolve(request, event_id, notification_type)
            template = CTFEmailTemplate.objects.filter(event=event, notification_type=notification_type).first()
            if template is None:
                _raise_not_found("No custom template to delete")
            template.delete(soft=True)
            return Response({"status": "reverted_to_default"})
        except _CtfApiError as exc:
            return exc.to_response(request)
