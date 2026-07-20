"""Notification and email-template JSON API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods, require_POST

if TYPE_CHECKING:
    from django.http import HttpRequest

    from ctf.models import (
        CTFEvent,
        CTFNotification,
    )

from ctf.views._access import (
    _get_user,
    _json_error,
    ctf_organizer_required,
)
from ctf.views._parsing import (
    _BodyParseError,
    _get_body_str,
    _parse_body_object,
)
from ctf.views.api._common import (
    _resolve_owned_event_json,
)

logger = logging.getLogger(__name__)


def _handle_notification_announce_post(request: HttpRequest, event: CTFEvent) -> JsonResponse:
    """Send an announcement from the POST body, returning a 201 payload or a 400 error."""
    from ctf.services import notification

    try:
        data = _parse_body_object(request)
        subject = _get_body_str(data, "subject").strip()
        body = _get_body_str(data, "body").strip()
        if not subject or not body:
            raise _BodyParseError("Subject and body are required")
    except _BodyParseError as e:
        return _json_error(e, "Invalid notification request.", 400)

    notif = notification.send_announcement(
        event_id=event.id,
        subject=subject,
        body=body,
        created_by=_get_user(request),
    )
    return JsonResponse(
        {
            "id": str(notif.id),
            "subject": notif.subject,
            "status": notif.status,
            "sent_count": notif.sent_count,
        },
        status=201,
    )


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def api_notification_list(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """API: List or create notifications.

    Args:
        event_id: UUID of the event.
    """
    from ctf.models import CTFNotification

    event, error = _resolve_owned_event_json(request, event_id)
    if error is not None:
        return error
    assert event is not None

    if request.method == "POST":
        return _handle_notification_announce_post(request, event)

    # GET: list notifications
    notifications = CTFNotification.objects.filter(event=event).order_by("-created_at")
    notification_list = [
        {
            "id": str(n.id),
            "notification_type": n.notification_type,
            "subject": n.subject,
            "status": n.status,
            "sent_count": n.sent_count,
            "created_at": n.created_at.isoformat(),
            "sent_at": n.sent_at.isoformat() if n.sent_at else None,
        }
        for n in notifications
    ]

    return JsonResponse({"notifications": notification_list})


def _notification_error_response(
    request: HttpRequest, html_message: str, json_message: str, status: int
) -> HttpResponse:
    """Return an HTML or JSON error per the request's Accept header."""
    if "text/html" in request.headers.get("Accept", ""):
        return HttpResponse(html_message, status=status)
    return JsonResponse({"error": json_message}, status=status)


def _dispatch_notification_send(notif: CTFNotification) -> None:
    """Send the notification via the handler matching its type (logging an unknown type)."""
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
        logger.warning("No handler for notification type: %s", notif.notification_type)


def _send_notification_response(request: HttpRequest, notif: CTFNotification) -> HttpResponse:
    """Send the notification and return an HTML redirect (browser) or JSON status."""
    _dispatch_notification_send(notif)

    # Browser form submission: redirect back to notification list
    if "text/html" in request.headers.get("Accept", ""):
        from django.shortcuts import redirect

        return redirect("ctf:admin_notification_list", event_id=notif.event_id)

    return JsonResponse(
        {
            "notification_id": str(notif.id),
            "status": "sent",
        }
    )


@login_required
@ctf_organizer_required
@require_POST
def api_notification_send(request: HttpRequest, notification_id: UUID) -> HttpResponse:
    """API: Send a notification.

    Args:
        notification_id: UUID of the notification.
    """
    from ctf.models import CTFNotification

    notif = CTFNotification.objects.select_related("event").filter(pk=notification_id).first()
    if not notif:
        return _notification_error_response(request, "Notification not found", "Notification not found", 404)

    if notif.event.created_by_id != request.user.pk:
        return _notification_error_response(
            request, "Forbidden: You do not have access to this event", "Forbidden", 403
        )

    return _send_notification_response(request, notif)


def _handle_get_email_template(event: CTFEvent, notification_type: str) -> JsonResponse:
    """Return the per-event custom template or 404."""
    from ctf.models import CTFEmailTemplate

    template = CTFEmailTemplate.objects.filter(event=event, notification_type=notification_type).first()
    if template is None:
        return JsonResponse({"error": "No custom template"}, status=404)
    return JsonResponse(
        {
            "id": str(template.id),
            "notification_type": template.notification_type,
            "subject": template.subject,
            "html_body": template.html_body,
            "text_body": template.text_body,
        }
    )


def _handle_delete_email_template(event: CTFEvent, notification_type: str) -> JsonResponse:
    """Soft-delete the per-event template; revert to default."""
    from ctf.models import CTFEmailTemplate

    template = CTFEmailTemplate.objects.filter(event=event, notification_type=notification_type).first()
    if template is None:
        return JsonResponse({"error": "No custom template to delete"}, status=404)
    template.delete(soft=True)
    return JsonResponse({"status": "reverted_to_default"})


def _email_body_error(label: str, source: str, allowed: frozenset[str]) -> str | None:
    """Return a validation error message for one email-template body, or None.

    Single exit point keeps `_validate_template_bodies` within the
    returns-per-function limit (python:S1142).
    """
    from ctf.services.email_template import find_template_violations

    if not source:
        return "html_body and text_body are required"
    violations = find_template_violations(source, allowed)
    if violations:
        return f"Invalid template syntax in {label}: {violations[0]}"
    return None


def _validate_template_bodies(html_body: str, text_body: str, notification_type: str) -> JsonResponse | None:
    """Validate the two organizer email-template bodies; return a 400 or None.

    Organizer templates are restricted to the flat ``{{ name }}`` placeholder
    grammar over the per-notification-type scalar allowlist enforced at render
    time (``ctf.services.email_template``). Request input is never compiled into
    a Django ``Template``; attribute traversal, filters, tags, comments, and
    unknown placeholders are rejected so untrusted template *logic* can never be
    stored and later rendered (CWE-1336, issue #1095).
    """
    from ctf.services.email_template import allowed_placeholders

    allowed = allowed_placeholders(notification_type)
    for label, source in (("html_body", html_body), ("text_body", text_body)):
        error = _email_body_error(label, source, allowed)
        if error:
            return JsonResponse({"error": error}, status=400)
    return None


def _handle_put_email_template(request: HttpRequest, event: CTFEvent, notification_type: str) -> JsonResponse:
    """Create or update a per-event email template from the PUT body, returning the payload or a 400."""
    from ctf.models import CTFEmailTemplate

    try:
        body = _parse_body_object(request)
        html_body = _get_body_str(body, "html_body").strip()
        text_body = _get_body_str(body, "text_body").strip()
        subject = _get_body_str(body, "subject").strip()
    except _BodyParseError as e:
        return _json_error(e, "Invalid notification request.", 400)

    syntax_error = _validate_template_bodies(html_body, text_body, notification_type)
    if syntax_error is not None:
        return syntax_error

    template, _created = CTFEmailTemplate.objects.update_or_create(
        event=event,
        notification_type=notification_type,
        defaults={
            "subject": subject,
            "html_body": html_body,
            "text_body": text_body,
        },
    )
    return JsonResponse(
        {
            "id": str(template.id),
            "notification_type": template.notification_type,
            "subject": template.subject,
            "html_body": template.html_body,
            "text_body": template.text_body,
        }
    )


def _dispatch_email_template_method(request: HttpRequest, event: CTFEvent, notification_type: str) -> JsonResponse:
    """Dispatch GET/DELETE/PUT for a resolved, owned event's email template override."""
    if request.method == "GET":
        return _handle_get_email_template(event, notification_type)
    if request.method == "DELETE":
        return _handle_delete_email_template(event, notification_type)
    return _handle_put_email_template(request, event, notification_type)


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "PUT", "DELETE"])
def api_event_email_template(request: HttpRequest, event_id: UUID, notification_type: str) -> JsonResponse:
    """API: Get, update, or delete a per-event email template override.

    GET returns the custom template (or 404 if using default).
    PUT creates or updates the custom template.
    DELETE removes the custom template (reverts to default).

    Args:
        event_id: UUID of the event.
        notification_type: Notification type string (e.g. "invitation").
    """
    from ctf.enums import NotificationType

    # Validate notification_type
    valid_types = {nt.value for nt in NotificationType}
    if notification_type not in valid_types:
        return JsonResponse({"error": f"Invalid notification type: {notification_type}"}, status=400)

    event, error = _resolve_owned_event_json(request, event_id)
    if error is not None:
        return error
    assert event is not None

    return _dispatch_email_template_method(request, event, notification_type)
