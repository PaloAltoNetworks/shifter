"""Organizer notification views for the canonical CTF API.

Announcements, notification dispatch, per-event email-template overrides, and the
send-invitations action.
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
from ctf.api.organizer._base import (
    _EVENT_READ,
    _EVENT_WRITE,
    _INVALID_NOTIFICATION,
    _NOTIFICATION_NOT_FOUND,
    _actor,
    _actor_may_manage,
    _pagination_window,
    _raise_bad_request,
    _raise_conflict,
    _raise_forbidden,
    _raise_not_found,
    _raise_throttled,
    _resolve_owned_event,
)
from ctf.api.serializers import (
    EmailTemplateResponseSerializer,
    EmailTemplateRevertResultSerializer,
    EmailTemplateWriteSerializer,
    NotificationAnnounceRequestSerializer,
    NotificationAnnounceResultSerializer,
    NotificationListResponseSerializer,
    NotificationSendResultSerializer,
    SendInvitationsResultSerializer,
)
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from django.contrib.auth.models import User

    from ctf.models import CTFEmailTemplate, CTFEvent, CTFNotification

logger = logging.getLogger(__name__)


def _dispatch_notification_send(notif: CTFNotification) -> None:
    """Send a notification via the handler matching its type (logging an unknown type).

    Mirrors ``ctf.views.api.notifications._dispatch_notification_send``.
    """
    from ctf.enums import NotificationType
    from ctf.services import notification

    type_dispatch = {
        NotificationType.INVITE.value: lambda n: notification.send_invitations(n.event_id),
        NotificationType.CREDENTIALS.value: lambda n: notification.send_credentials(n.event_id),
        NotificationType.REMINDER.value: lambda n: notification.send_reminder(n.event_id),
        NotificationType.ANNOUNCEMENT.value: lambda n: notification.send_announcement(
            n.event_id, n.subject, n.body, n.created_by
        ),
    }
    handler = type_dispatch.get(notif.notification_type)
    if handler:
        handler(notif)
    else:
        logger.warning("No handler for notification type: %s", safe_log_value(str(notif.notification_type)))


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


class SendInvitationsView(APIView):
    """Send invitation emails to all uninvited participants of an owned event."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_write_scopes = _EVENT_WRITE

    @extend_schema(request=None, responses=SendInvitationsResultSerializer)
    def post(self, request: Request, event_id: UUID) -> Response:
        """Rate-limit, enforce ownership, then queue the invitation emails."""
        from ctf.services.notification import send_invitations
        from ctf.views._access import _check_credential_delivery_rate_limit

        try:
            if not _check_credential_delivery_rate_limit(_actor(request).pk):
                _raise_throttled("Too many invitations. Try again later.")
            _resolve_owned_event(request, event_id, capability="notifications")
            result = send_invitations(event_id)
            return Response({"success": True, **result})
        except _CtfApiError as exc:
            return exc.to_response(request)


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

    @extend_schema(request=NotificationAnnounceRequestSerializer, responses={201: NotificationAnnounceResultSerializer})
    def post(self, request: Request, event_id: UUID) -> Response:
        """Send an announcement to an owned event from the request body."""
        from ctf.services import notification

        try:
            event = _resolve_owned_event(request, event_id, capability="notifications")
            serializer = NotificationAnnounceRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            subject = serializer.validated_data["subject"].strip()
            body = serializer.validated_data["body"].strip()
            if not subject or not body:
                _raise_bad_request(_INVALID_NOTIFICATION)
            scheduled_at = serializer.validated_data.get("scheduled_at")
            if scheduled_at is not None:
                notif = self._schedule(event, subject, body, _actor(request), scheduled_at)
            else:
                notif = notification.send_announcement(
                    event_id=event.id,
                    subject=subject,
                    body=body,
                    created_by=_actor(request),
                )
            return Response(
                {
                    "id": str(notif.id),
                    "subject": notif.subject,
                    "status": notif.status,
                    "sent_count": notif.sent_count,
                },
                status=status.HTTP_201_CREATED,
            )
        except _CtfApiError as exc:
            return exc.to_response(request)

    @staticmethod
    def _schedule(
        event: CTFEvent,
        subject: str,
        body: str,
        actor: User,
        scheduled_at: datetime,
    ) -> CTFNotification:
        """Create a draft announcement and schedule it for future delivery (CTF-804)."""
        from django.utils import timezone as dj_timezone

        from ctf.enums import NotificationStatus, NotificationType
        from ctf.models import CTFNotification
        from ctf.services.notification import schedule_notification

        if scheduled_at <= dj_timezone.now():
            _raise_bad_request("Scheduled time must be in the future")
        notif = CTFNotification.objects.create(
            event=event,
            notification_type=NotificationType.ANNOUNCEMENT.value,
            subject=subject,
            body=body,
            status=NotificationStatus.DRAFT.value,
            recipient_filter="participants",
            created_by=actor,
        )
        return schedule_notification(notif.pk, scheduled_at)


class NotificationCancelScheduleView(APIView):
    """Cancel a scheduled notification before delivery (POST, CTF-804)."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_write_scopes = _EVENT_WRITE

    @extend_schema(request=None, responses=NotificationSendResultSerializer)
    def post(self, request: Request, notification_id: UUID) -> Response:
        """Revert the notification to draft and cancel its scheduler task."""
        from ctf.exceptions import CTFStateError
        from ctf.models import CTFNotification
        from ctf.services.notification import cancel_scheduled_notification

        try:
            notif = CTFNotification.objects.select_related("event").filter(pk=notification_id).first()
            if not notif:
                _raise_not_found(_NOTIFICATION_NOT_FOUND)
            if not _actor_may_manage(request, notif.event, "notifications"):
                _raise_forbidden()
            try:
                cancel_scheduled_notification(notification_id)
            except CTFStateError as exc:
                _raise_conflict(str(exc))
            return Response({"notification_id": str(notification_id), "status": "cancelled"})
        except _CtfApiError as exc:
            return exc.to_response(request)


class NotificationSendView(APIView):
    """Dispatch a notification to its recipients (organizer)."""

    permission_classes = CTF_ORGANIZER_PERMISSIONS
    required_write_scopes = _EVENT_WRITE

    @extend_schema(request=None, responses=NotificationSendResultSerializer)
    def post(self, request: Request, notification_id: UUID) -> Response:
        """Resolve the notification, enforce ownership, then send it."""
        from ctf.models import CTFNotification

        try:
            notif = CTFNotification.objects.select_related("event").filter(pk=notification_id).first()
            if not notif:
                _raise_not_found(_NOTIFICATION_NOT_FOUND)
            if not _actor_may_manage(request, notif.event, "notifications"):
                _raise_forbidden()
            _dispatch_notification_send(notif)
            return Response({"notification_id": str(notif.id), "status": "sent"})
        except _CtfApiError as exc:
            return exc.to_response(request)


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
