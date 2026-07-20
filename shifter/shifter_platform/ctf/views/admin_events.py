"""Organizer/admin event-management HTML views."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods

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

_EVENT_NOT_FOUND_MSG = "Event not found"
_FORBIDDEN_EVENT_MSG = "Forbidden: You do not have access to this event"


@login_required
@ctf_organizer_required
def admin_dashboard(request: HttpRequest) -> HttpResponse:
    """Organizer main dashboard.

    Shows overview of all events, quick actions, range status, and activity feed.
    """
    from django.db.models import Count

    from ctf.enums import EventStatus
    from ctf.forms import EventStatusForm
    from ctf.models import CTFParticipant, CTFSubmission
    from ctf.services import get_event_stats, get_organizer_events

    # Get all events first for counting
    all_events = get_organizer_events(_get_user(request))

    active_count = all_events.filter(status=EventStatus.ACTIVE.value).count()
    upcoming_count = all_events.filter(status=EventStatus.REGISTRATION.value).count()
    draft_count = all_events.filter(status=EventStatus.DRAFT.value).count()

    # Get recent 5 events for display
    recent_events = list(all_events[:5])

    # Active events with stats, range summary, and status controls
    active_events = list(all_events.filter(status=EventStatus.ACTIVE.value)[:5])
    active_event_ids = [evt.id for evt in active_events]

    # Batch range status aggregation across all active events (single query)
    range_by_event: dict[str, dict[str, int]] = {}
    range_ready = 0
    range_provisioning = 0
    range_error = 0
    if active_event_ids:
        range_rows = (
            CTFParticipant.objects.filter(event_id__in=active_event_ids)
            .exclude(range_status="")
            .values("event_id", "range_status")
            .annotate(c=Count("id"))
        )
        for row in range_rows:
            eid = str(row["event_id"])
            status = row["range_status"]
            count = row["c"]
            range_by_event.setdefault(eid, {})[status] = count
            if status == "ready":
                range_ready += count
            elif status == "provisioning":
                range_provisioning += count
            elif status == "error":
                range_error += count

    active_events_data = []
    for evt in active_events:
        stats = get_event_stats(evt)
        status_form = EventStatusForm(event=evt)
        evt_ranges = range_by_event.get(str(evt.id), {})

        active_events_data.append(
            {
                "event": evt,
                "stats": stats,
                "status_form": status_form,
                "range_ready": evt_ranges.get("ready", 0),
                "range_provisioning": evt_ranges.get("provisioning", 0),
                "range_error": evt_ranges.get("error", 0),
            }
        )

    # Recent activity feed — last 15 submissions across active events
    recent_activity = []
    if active_event_ids:
        recent_activity = list(
            CTFSubmission.objects.filter(participant__event_id__in=active_event_ids)
            .select_related("participant", "challenge")
            .order_by("-submitted_at")[:15]
        )

    context = {
        "recent_events": recent_events,
        "active_count": active_count,
        "upcoming_count": upcoming_count,
        "draft_count": draft_count,
        "total_events": all_events.count(),
        "active_events_data": active_events_data,
        "recent_activity": recent_activity,
        "range_ready": range_ready,
        "range_provisioning": range_provisioning,
        "range_error": range_error,
    }

    return render(request, "ctf/admin/dashboard.html", context)


@login_required
@ctf_organizer_required
def admin_event_list(request: HttpRequest) -> HttpResponse:
    """Organizer event list.

    Shows all events created by the organizer with optional filtering.
    """
    from ctf.services import get_organizer_events

    status_filter = request.GET.get("status")
    events = get_organizer_events(_get_user(request), status=status_filter)

    # Get status choices for filter dropdown
    from ctf.enums import EventStatus

    status_choices = EventStatus.choices()

    context = {
        "events": events,
        "status_filter": status_filter,
        "status_choices": status_choices,
    }

    return render(request, "ctf/admin/event_list.html", context)


@login_required
@ctf_organizer_required
@require_GET
def admin_event_create(request: HttpRequest) -> HttpResponse:
    """Show CTF event creation form.

    Renders the form template with scenario data. The form submits
    via fetch() to the event API endpoint.
    """
    from ctf.bridges import cms_list_scenarios

    user = _get_user(request)
    scenarios = cms_list_scenarios(user)
    scenarios_list = [{"id": sid, "name": name} for sid, name in scenarios]
    return render(
        request,
        "ctf/admin/event_form.html",
        {
            "is_edit": False,
            "scenarios_list": scenarios_list,
        },
    )


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def admin_event_detail(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Event detail view for organizers.

    Shows event information, statistics, and status change controls.

    Args:
        event_id: UUID of the event.
    """
    from django.http import Http404
    from django.shortcuts import redirect

    from ctf.exceptions import CTFNotFoundError
    from ctf.forms import EventStatusForm
    from ctf.services import (
        activate_event,
        archive_event,
        cancel_event,
        complete_event,
        get_event,
        get_event_stats,
        pause_event,
        resume_event,
        schedule_event,
    )

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        raise Http404(_EVENT_NOT_FOUND_MSG) from None

    # Check permission - organizers can only access their own events
    if event.created_by_id != request.user.pk:
        return HttpResponse(_FORBIDDEN_EVENT_MSG, status=403)

    if request.method == "POST":
        status_form = EventStatusForm(request.POST, event=event)
        if status_form.is_valid():
            action = status_form.cleaned_data["action"]
            action_table = {
                "schedule": schedule_event,
                "activate": activate_event,
                "pause": pause_event,
                "resume": resume_event,
                "complete": complete_event,
                "archive": archive_event,
                "cancel": cancel_event,
            }
            handler = action_table.get(action)
            success = handler(event) if handler else False
            if success:
                logger.info(
                    "User %s changed event %s status via action: %s",
                    request.user.email,
                    event.pk,
                    action,
                )
            return redirect("ctf:admin_event_detail", event_id=event.pk)
    else:
        status_form = EventStatusForm(event=event)

    stats = get_event_stats(event)

    context = {
        "event": event,
        "stats": stats,
        "status_form": status_form,
    }

    return render(request, "ctf/admin/event_detail.html", context)


def _handle_event_force_delete_post(request: HttpRequest, event: CTFEvent, event_id: UUID) -> HttpResponse:
    """Perform the force delete after name confirmation, re-rendering on mismatch."""
    from django.contrib import messages
    from django.shortcuts import redirect

    from ctf.exceptions import CTFValidationError
    from ctf.services import force_delete_event, get_event_stats

    user = _get_user(request)
    confirmation_name = request.POST.get("confirmation_name", "")
    try:
        result = force_delete_event(event_id, user, confirmation_name)
    except CTFValidationError:
        stats = get_event_stats(event)
        return render(
            request,
            "ctf/admin/event_force_delete.html",
            {
                "event": event,
                "stats": stats,
                "error": "The name you typed does not match. Please try again.",
            },
        )

    messages.success(
        request,
        f"Event '{result['event_name']}' has been permanently deleted. Ranges destroyed: {result['ranges_destroyed']}.",
    )
    return redirect("ctf:admin_event_list")


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def admin_event_force_delete(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Force-delete confirmation page and handler.

    GET renders a confirmation page where the organizer must type the event
    name to confirm. POST performs the force delete and redirects to the
    event list.

    Args:
        event_id: UUID of the event.
    """
    from django.http import Http404

    from ctf.models import CTFEvent
    from ctf.services import get_event_stats

    try:
        event = CTFEvent.all_objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise Http404(_EVENT_NOT_FOUND_MSG) from None

    if event.created_by_id != request.user.pk:
        return HttpResponse(_FORBIDDEN_EVENT_MSG, status=403)

    if request.method == "GET":
        stats = get_event_stats(event)
        return render(
            request,
            "ctf/admin/event_force_delete.html",
            {"event": event, "stats": stats},
        )

    return _handle_event_force_delete_post(request, event, event_id)


@login_required
@ctf_organizer_required
@require_GET
def admin_event_edit(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Show CTF event edit form.

    Renders the form template with event and scenario data. The form
    submits via fetch() PUT to the event detail API endpoint.

    Args:
        event_id: UUID of the event.
    """
    from django.http import Http404

    from ctf.bridges import cms_list_scenarios
    from ctf.exceptions import CTFNotFoundError
    from ctf.services import get_event

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        raise Http404(_EVENT_NOT_FOUND_MSG) from None

    # Check permission - organizers can only access their own events
    if event.created_by_id != request.user.pk:
        return HttpResponse(_FORBIDDEN_EVENT_MSG, status=403)

    # Check if event is modifiable
    if not event.is_modifiable:
        logger.warning(
            "User %s attempted to edit non-modifiable event %s",
            request.user.email,
            event.pk,
        )
        return redirect("ctf:admin_event_detail", event_id=event.pk)

    user = _get_user(request)
    scenarios = cms_list_scenarios(user)
    scenarios_list = [{"id": sid, "name": name} for sid, name in scenarios]
    return render(
        request,
        "ctf/admin/event_form.html",
        {
            "is_edit": True,
            "event_id": str(event_id),
            "scenarios_list": scenarios_list,
        },
    )


@login_required
@ctf_organizer_required
@require_http_methods(["GET"])
def admin_event_email_templates(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """List email template overrides for an event.

    Shows all notification types with their current template status
    (default or custom).

    Args:
        event_id: UUID of the event.
    """
    from django.http import Http404

    from ctf.enums import NotificationType
    from ctf.exceptions import CTFNotFoundError
    from ctf.models import CTFEmailTemplate
    from ctf.services import get_event

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        raise Http404(_EVENT_NOT_FOUND_MSG) from None

    if event.created_by_id != request.user.pk:
        return HttpResponse(_FORBIDDEN_EVENT_MSG, status=403)

    custom_templates = {t.notification_type: t for t in CTFEmailTemplate.objects.filter(event=event)}

    template_list = []
    for nt in NotificationType:
        template_list.append(
            {
                "type": nt.value,
                "label": nt.value.replace("_", " ").title(),
                "custom": custom_templates.get(nt.value),
            }
        )

    return render(
        request,
        "ctf/admin/email_templates.html",
        {"event": event, "template_list": template_list},
    )


@login_required
@ctf_organizer_required
def admin_analytics(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Analytics view for an event.

    Args:
        event_id: UUID of the event.
    """
    from django.http import Http404

    from ctf.exceptions import CTFNotFoundError
    from ctf.services import get_event

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        raise Http404(_EVENT_NOT_FOUND_MSG) from None

    if event.created_by_id != request.user.pk:
        return HttpResponse(_FORBIDDEN_EVENT_MSG, status=403)

    from ctf.models import CTFChallenge
    from ctf.services import get_challenge_statistics, get_event_statistics

    event_stats = get_event_statistics(event.id)

    challenges = CTFChallenge.objects.filter(event=event).order_by("category", "order", "name")
    challenge_stats = []
    for c in challenges:
        stats = get_challenge_statistics(c.id)
        stats["name"] = c.name
        stats["category"] = c.get_category_display()
        stats["points"] = c.points
        challenge_stats.append(stats)

    return render(
        request,
        "ctf/admin/analytics.html",
        {
            "event": event,
            "event_stats": event_stats,
            "challenge_stats": challenge_stats,
        },
    )
