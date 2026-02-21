"""CTF views.

This module provides view functions for the CTF management platform.
Views are organized into:
- Participant views (for CTF competitors)
- Admin/Organizer views (for event managers)
- API views (for AJAX/programmatic access)

All views require authentication unless otherwise noted.
"""

from __future__ import annotations

import functools
import logging
from typing import TYPE_CHECKING
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from management.services import get_user_profile

if TYPE_CHECKING:
    from django.http import HttpRequest

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Decorators
# -----------------------------------------------------------------------------


def ctf_organizer_required(view_func):
    """Decorator that requires the user to be a CTF organizer.

    Returns 403 Forbidden if user is not an organizer.
    Must be used after @login_required.
    """

    @functools.wraps(view_func)
    def wrapper(request: HttpRequest, *args, **kwargs):
        profile = get_user_profile(request.user)
        if not profile.is_ctf_organizer:
            logger.warning(
                "CTF organizer access denied for user %s",
                request.user.email if request.user.is_authenticated else "anonymous",
            )
            return HttpResponse("Forbidden: CTF organizer access required", status=403)
        return view_func(request, *args, **kwargs)

    return wrapper


def ctf_participant_required(view_func):
    """Decorator that requires the user to be a CTF participant.

    Returns 403 Forbidden if user is not a participant.
    Must be used after @login_required.
    """

    @functools.wraps(view_func)
    def wrapper(request: HttpRequest, *args, **kwargs):
        profile = get_user_profile(request.user)
        if not profile.is_ctf_participant:
            logger.warning(
                "CTF participant access denied for user %s",
                request.user.email if request.user.is_authenticated else "anonymous",
            )
            return HttpResponse("Forbidden: CTF participant access required", status=403)
        return view_func(request, *args, **kwargs)

    return wrapper


# -----------------------------------------------------------------------------
# Participant Views (CTF Competitors)
# -----------------------------------------------------------------------------


def ctf_login(request: HttpRequest) -> HttpResponse:
    """CTF-specific login page.

    Handles login for CTF participants with optional event/invite token params.
    Accepts query parameters:
    - event: UUID of the event to show context for
    - token: Invite token for participant registration
    """
    context: dict = {}

    event_id = request.GET.get("event")
    invite_token = request.GET.get("token")

    if event_id:
        from ctf.models import CTFEvent

        try:
            event = CTFEvent.objects.get(pk=event_id)
            context["event"] = event
        except (CTFEvent.DoesNotExist, ValueError):
            logger.warning("CTF login: invalid event_id %s", event_id)

    if invite_token:
        from ctf.models import CTFParticipant

        participant = CTFParticipant.objects.filter(invite_token=invite_token).first()
        if participant:
            context["invite_participant"] = participant
            context["invite_valid"] = participant.is_invite_valid
            if not context.get("event"):
                context["event"] = participant.event
        else:
            logger.warning("CTF login: invalid invite token")

    return render(request, "ctf/login.html", context)


@login_required
@ctf_participant_required
def participant_dashboard(request: HttpRequest) -> HttpResponse:
    """Participant main dashboard.

    Shows event overview, challenge progress, and quick links.
    """
    # TODO: Implement participant dashboard
    return render(request, "ctf/participant/dashboard.html", {"placeholder": True})


@login_required
@ctf_participant_required
def participant_event(request: HttpRequest) -> HttpResponse:
    """Participant event detail view.

    Shows current event information and status.
    """
    # TODO: Implement event detail view
    return render(request, "ctf/participant/event.html", {"placeholder": True})


@login_required
@ctf_participant_required
def participant_challenges(request: HttpRequest) -> HttpResponse:
    """Participant challenges list.

    Shows available challenges with solve status.
    """
    # TODO: Implement challenges list
    return render(request, "ctf/participant/challenges.html", {"placeholder": True})


@login_required
@ctf_participant_required
def challenge_detail(request: HttpRequest, challenge_id: UUID) -> HttpResponse:
    """Participant challenge detail with submission form.

    Args:
        challenge_id: UUID of the challenge.
    """
    # TODO: Implement challenge detail view
    return render(
        request,
        "ctf/participant/challenge_detail.html",
        {"placeholder": True, "challenge_id": challenge_id},
    )


@login_required
@ctf_participant_required
def participant_range(request: HttpRequest) -> HttpResponse:
    """Participant range status and access.

    Shows range provisioning status and access URLs.
    """
    # TODO: Implement range view
    return render(request, "ctf/participant/range.html", {"placeholder": True})


@login_required
@ctf_participant_required
def scoreboard(request: HttpRequest) -> HttpResponse:
    """Public scoreboard view.

    Shows rankings for current event.
    """
    # TODO: Implement scoreboard view
    return render(request, "ctf/participant/scoreboard.html", {"placeholder": True})


@login_required
@ctf_participant_required
def participant_team(request: HttpRequest) -> HttpResponse:
    """Participant team view.

    Shows team members and team-specific information.
    """
    # TODO: Implement team view
    return render(request, "ctf/participant/team.html", {"placeholder": True})


@login_required
@ctf_participant_required
def team_join(request: HttpRequest) -> HttpResponse:
    """Join a team using invite code.

    GET: Show join form.
    POST: Process join request.
    """
    # TODO: Implement team join
    return render(request, "ctf/participant/team_join.html", {"placeholder": True})


def ctf_help(request: HttpRequest) -> HttpResponse:
    """CTF help page.

    Public help page for CTF participants.
    """
    return render(request, "ctf/help.html", {"placeholder": True})


# -----------------------------------------------------------------------------
# Admin/Organizer Views
# -----------------------------------------------------------------------------


@login_required
@ctf_organizer_required
def admin_dashboard(request: HttpRequest) -> HttpResponse:
    """Organizer main dashboard.

    Shows overview of all events and quick actions.
    """
    # TODO: Implement admin dashboard
    return render(request, "ctf/admin/dashboard.html", {"placeholder": True})


@login_required
@ctf_organizer_required
def admin_event_list(request: HttpRequest) -> HttpResponse:
    """Organizer event list.

    Shows all events created by the organizer.
    """
    # TODO: Implement event list
    return render(request, "ctf/admin/event_list.html", {"placeholder": True})


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def admin_event_create(request: HttpRequest) -> HttpResponse:
    """Create new CTF event.

    GET: Show creation form.
    POST: Process creation.
    """
    # TODO: Implement event creation
    return render(request, "ctf/admin/event_form.html", {"placeholder": True})


@login_required
@ctf_organizer_required
def admin_event_detail(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Event detail view for organizers.

    Args:
        event_id: UUID of the event.
    """
    # TODO: Implement event detail
    return render(
        request,
        "ctf/admin/event_detail.html",
        {"placeholder": True, "event_id": event_id},
    )


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def admin_event_edit(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Edit CTF event.

    Args:
        event_id: UUID of the event.
    """
    # TODO: Implement event edit
    return render(
        request,
        "ctf/admin/event_form.html",
        {"placeholder": True, "event_id": event_id},
    )


@login_required
@ctf_organizer_required
def admin_challenge_list(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Challenge list for an event.

    Args:
        event_id: UUID of the event.
    """
    # TODO: Implement challenge list
    return render(
        request,
        "ctf/admin/challenge_list.html",
        {"placeholder": True, "event_id": event_id},
    )


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def admin_challenge_create(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Create new challenge.

    Args:
        event_id: UUID of the event.
    """
    # TODO: Implement challenge creation
    return render(
        request,
        "ctf/admin/challenge_form.html",
        {"placeholder": True, "event_id": event_id},
    )


@login_required
@ctf_organizer_required
def admin_challenge_detail(request: HttpRequest, challenge_id: UUID) -> HttpResponse:
    """Challenge detail view.

    Args:
        challenge_id: UUID of the challenge.
    """
    # TODO: Implement challenge detail
    return render(
        request,
        "ctf/admin/challenge_detail.html",
        {"placeholder": True, "challenge_id": challenge_id},
    )


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def admin_challenge_edit(request: HttpRequest, challenge_id: UUID) -> HttpResponse:
    """Edit challenge.

    Args:
        challenge_id: UUID of the challenge.
    """
    # TODO: Implement challenge edit
    return render(
        request,
        "ctf/admin/challenge_form.html",
        {"placeholder": True, "challenge_id": challenge_id},
    )


@login_required
@ctf_organizer_required
def admin_participant_list(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Participant list for an event.

    Args:
        event_id: UUID of the event.
    """
    # TODO: Implement participant list
    return render(
        request,
        "ctf/admin/participant_list.html",
        {"placeholder": True, "event_id": event_id},
    )


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def admin_participant_import(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Import participants from CSV.

    Args:
        event_id: UUID of the event.
    """
    # TODO: Implement participant import
    return render(
        request,
        "ctf/admin/participant_import.html",
        {"placeholder": True, "event_id": event_id},
    )


@login_required
@ctf_organizer_required
def admin_participant_detail(request: HttpRequest, participant_id: UUID) -> HttpResponse:
    """Participant detail view.

    Args:
        participant_id: UUID of the participant.
    """
    # TODO: Implement participant detail
    return render(
        request,
        "ctf/admin/participant_detail.html",
        {"placeholder": True, "participant_id": participant_id},
    )


@login_required
@ctf_organizer_required
def admin_team_list(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Team list for an event.

    Args:
        event_id: UUID of the event.
    """
    # TODO: Implement team list
    return render(
        request,
        "ctf/admin/team_list.html",
        {"placeholder": True, "event_id": event_id},
    )


@login_required
@ctf_organizer_required
def admin_scoreboard(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Admin scoreboard view with extra details.

    Args:
        event_id: UUID of the event.
    """
    # TODO: Implement admin scoreboard
    return render(
        request,
        "ctf/admin/scoreboard.html",
        {"placeholder": True, "event_id": event_id},
    )


@login_required
@ctf_organizer_required
def admin_range_list(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Range status overview for an event.

    Args:
        event_id: UUID of the event.
    """
    # TODO: Implement range list
    return render(
        request,
        "ctf/admin/range_list.html",
        {"placeholder": True, "event_id": event_id},
    )


@login_required
@ctf_organizer_required
def admin_notification_list(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Notification list for an event.

    Args:
        event_id: UUID of the event.
    """
    # TODO: Implement notification list
    return render(
        request,
        "ctf/admin/notification_list.html",
        {"placeholder": True, "event_id": event_id},
    )


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def admin_notification_create(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Create new notification.

    Args:
        event_id: UUID of the event.
    """
    # TODO: Implement notification creation
    return render(
        request,
        "ctf/admin/notification_form.html",
        {"placeholder": True, "event_id": event_id},
    )


@login_required
@ctf_organizer_required
def admin_analytics(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Analytics view for an event.

    Args:
        event_id: UUID of the event.
    """
    # TODO: Implement analytics
    return render(
        request,
        "ctf/admin/analytics.html",
        {"placeholder": True, "event_id": event_id},
    )


# -----------------------------------------------------------------------------
# API Views
# -----------------------------------------------------------------------------


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def api_event_list(request: HttpRequest) -> JsonResponse:
    """API: List events or create new event.

    GET: List events for organizer.
    POST: Create new event.
    """
    # TODO: Implement event list/create API
    return JsonResponse({"placeholder": True, "method": request.method})


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "PUT", "DELETE"])
def api_event_detail(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """API: Get, update, or delete event.

    Args:
        event_id: UUID of the event.
    """
    # TODO: Implement event detail API
    return JsonResponse(
        {"placeholder": True, "event_id": str(event_id), "method": request.method}
    )


@login_required
@require_http_methods(["GET", "POST"])
def api_challenge_list(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """API: List challenges or create new challenge.

    Args:
        event_id: UUID of the event.
    """
    # TODO: Implement challenge list/create API
    return JsonResponse(
        {"placeholder": True, "event_id": str(event_id), "method": request.method}
    )


@login_required
@require_http_methods(["GET", "PUT", "DELETE"])
def api_challenge_detail(request: HttpRequest, challenge_id: UUID) -> JsonResponse:
    """API: Get, update, or delete challenge.

    Args:
        challenge_id: UUID of the challenge.
    """
    # TODO: Implement challenge detail API
    return JsonResponse(
        {"placeholder": True, "challenge_id": str(challenge_id), "method": request.method}
    )


@login_required
@require_POST
def api_submit_flag(request: HttpRequest, challenge_id: UUID) -> JsonResponse:
    """API: Submit flag for a challenge.

    Args:
        challenge_id: UUID of the challenge.
    """
    # TODO: Implement flag submission API
    return JsonResponse({"placeholder": True, "challenge_id": str(challenge_id)})


@login_required
@require_POST
def api_use_hint(request: HttpRequest, challenge_id: UUID) -> JsonResponse:
    """API: Use hint for a challenge.

    Args:
        challenge_id: UUID of the challenge.
    """
    # TODO: Implement hint usage API
    return JsonResponse({"placeholder": True, "challenge_id": str(challenge_id)})


@login_required
@require_GET
def api_submissions(request: HttpRequest) -> JsonResponse:
    """API: Get submissions for current user."""
    # TODO: Implement submissions list API
    return JsonResponse({"placeholder": True, "submissions": []})


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def api_participant_list(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """API: List participants or add new participant.

    Args:
        event_id: UUID of the event.
    """
    # TODO: Implement participant list/create API
    return JsonResponse(
        {"placeholder": True, "event_id": str(event_id), "method": request.method}
    )


@login_required
@ctf_organizer_required
@require_POST
def api_participant_import(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """API: Bulk import participants.

    Args:
        event_id: UUID of the event.
    """
    # TODO: Implement participant import API
    return JsonResponse({"placeholder": True, "event_id": str(event_id)})


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "DELETE"])
def api_participant_detail(request: HttpRequest, participant_id: UUID) -> JsonResponse:
    """API: Get or remove participant.

    Args:
        participant_id: UUID of the participant.
    """
    # TODO: Implement participant detail API
    return JsonResponse(
        {"placeholder": True, "participant_id": str(participant_id), "method": request.method}
    )


@login_required
@require_GET
def api_range_status(request: HttpRequest) -> JsonResponse:
    """API: Get range status for current participant."""
    # TODO: Implement range status API
    return JsonResponse({"placeholder": True, "status": "not_assigned"})


@login_required
@require_POST
def api_range_access(request: HttpRequest) -> JsonResponse:
    """API: Get range access URL."""
    # TODO: Implement range access API
    return JsonResponse({"placeholder": True, "url": None})


@login_required
@require_GET
def api_scoreboard(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """API: Get scoreboard data.

    Args:
        event_id: UUID of the event.
    """
    # TODO: Implement scoreboard API
    return JsonResponse({"placeholder": True, "event_id": str(event_id), "rankings": []})


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def api_notification_list(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """API: List or create notifications.

    Args:
        event_id: UUID of the event.
    """
    # TODO: Implement notification list/create API
    return JsonResponse(
        {"placeholder": True, "event_id": str(event_id), "method": request.method}
    )


@login_required
@ctf_organizer_required
@require_POST
def api_notification_send(request: HttpRequest, notification_id: UUID) -> JsonResponse:
    """API: Send a notification.

    Args:
        notification_id: UUID of the notification.
    """
    # TODO: Implement notification send API
    return JsonResponse({"placeholder": True, "notification_id": str(notification_id)})
