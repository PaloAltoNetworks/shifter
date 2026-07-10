"""Organizer/admin notification-management HTML views."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

if TYPE_CHECKING:
    from django.http import HttpRequest

    from ctf.models import (
        CTFEvent,
    )

from ctf.views._access import (
    _get_user,
    ctf_organizer_required,
)

logger = logging.getLogger(__name__)

_NOTIFICATION_FORM_TEMPLATE = "ctf/admin/notification_form.html"


@login_required
@ctf_organizer_required
def admin_notification_list(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Notification list for an event.

    Args:
        event_id: UUID of the event.
    """
    from django.http import Http404

    from ctf.exceptions import CTFNotFoundError
    from ctf.models import CTFNotification
    from ctf.services import get_event

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        raise Http404("Event not found") from None

    if event.created_by_id != request.user.pk:
        return HttpResponse("Forbidden: You do not have access to this event", status=403)

    notifications = CTFNotification.objects.filter(event=event).order_by("-created_at")

    return render(
        request,
        "ctf/admin/notification_list.html",
        {"event": event, "notifications": notifications},
    )


def _resolve_owned_event_or_404(request: HttpRequest, event_id: UUID) -> tuple[CTFEvent | None, HttpResponse | None]:
    """Resolve an event (Http404 if missing) and enforce ownership; return (event, error_response)."""
    from django.http import Http404

    from ctf.exceptions import CTFNotFoundError
    from ctf.services import get_event

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        raise Http404("Event not found") from None

    if event.created_by_id != request.user.pk:
        return None, HttpResponse("Forbidden: You do not have access to this event", status=403)

    return event, None


def _handle_notification_create_post(request: HttpRequest, event: CTFEvent) -> HttpResponse:
    """Create, schedule, or send an announcement notification; re-render the form on error."""
    from ctf.enums import NotificationStatus, NotificationType
    from ctf.models import CTFNotification
    from ctf.services import notification

    subject = request.POST.get("subject", "").strip()
    body = request.POST.get("body", "").strip()
    action = request.POST.get("action", "draft")

    if not subject or not body:
        return render(
            request,
            _NOTIFICATION_FORM_TEMPLATE,
            {"event": event, "error": "Subject and body are required."},
        )

    if action == "send_now":
        notification.send_announcement(
            event_id=event.id,
            subject=subject,
            body=body,
            created_by=_get_user(request),
        )
    elif action == "schedule":
        from django.utils.dateparse import parse_datetime

        scheduled_at = parse_datetime(request.POST.get("scheduled_at", ""))
        if not scheduled_at:
            return render(
                request,
                _NOTIFICATION_FORM_TEMPLATE,
                {"event": event, "error": "Valid schedule time is required."},
            )
        notif = CTFNotification.objects.create(
            event=event,
            notification_type=NotificationType.ANNOUNCEMENT.value,
            subject=subject,
            body=body,
            status=NotificationStatus.DRAFT.value,
            recipient_filter="participants",
            created_by=_get_user(request),
        )
        notification.schedule_notification(notif.id, scheduled_at)
    else:
        # Save as draft
        CTFNotification.objects.create(
            event=event,
            notification_type=NotificationType.ANNOUNCEMENT.value,
            subject=subject,
            body=body,
            status=NotificationStatus.DRAFT.value,
            recipient_filter="participants",
            created_by=_get_user(request),
        )

    return redirect("ctf:admin_notification_list", event_id=event.id)


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def admin_notification_create(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Create new notification.

    Args:
        event_id: UUID of the event.
    """
    event, error = _resolve_owned_event_or_404(request, event_id)
    if error is not None:
        return error
    assert event is not None

    if request.method == "POST":
        return _handle_notification_create_post(request, event)

    return render(
        request,
        _NOTIFICATION_FORM_TEMPLATE,
        {"event": event},
    )
