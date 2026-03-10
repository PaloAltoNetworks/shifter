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
# Helpers
# -----------------------------------------------------------------------------


def _get_client_ip(request):
    """Extract client IP from request headers."""
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


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
    from ctf.services.challenge import get_available_challenges
    from ctf.services.participant import get_participant_by_user
    from ctf.services.scoring import calculate_score, get_participant_rank

    participant = get_participant_by_user(request.user)
    if not participant:
        return render(request, "ctf/participant/dashboard.html", {})

    event = participant.event
    score = calculate_score(participant.id)
    rank = get_participant_rank(participant.id)
    solved_count = participant.solved_challenge_count
    total_challenges = get_available_challenges(event.id).count()

    context = {
        "participant": participant,
        "event": event,
        "score": score,
        "rank": rank,
        "solved_count": solved_count,
        "total_challenges": total_challenges,
    }
    return render(request, "ctf/participant/dashboard.html", context)


@login_required
@ctf_participant_required
def participant_event(request: HttpRequest) -> HttpResponse:
    """Participant event detail view.

    Shows current event information and status.
    """
    from ctf.services.participant import get_participant_by_user

    participant = get_participant_by_user(request.user)
    if not participant:
        return render(request, "ctf/participant/event.html", {})

    event = participant.event

    context = {
        "participant": participant,
        "event": event,
    }
    return render(request, "ctf/participant/event.html", context)


@login_required
@ctf_participant_required
def participant_challenges(request: HttpRequest) -> HttpResponse:
    """Participant challenges list.

    Shows available challenges with solve status.
    """
    from collections import defaultdict

    from ctf.services.challenge import get_available_challenges
    from ctf.services.participant import get_participant_by_user
    from ctf.services.submission import get_participant_submissions

    participant = get_participant_by_user(request.user)
    if not participant:
        return render(request, "ctf/participant/challenges.html", {})

    event = participant.event
    challenges = get_available_challenges(event.id)

    # Apply category filter if provided
    category_filter = request.GET.get("category")
    if category_filter:
        challenges = challenges.filter(category=category_filter)

    # Build set of solved challenge IDs
    correct_submissions = get_participant_submissions(participant.id).filter(is_correct=True)
    solved_ids = set(correct_submissions.values_list("challenge_id", flat=True))

    # Annotate challenges with solve status
    challenge_list = []
    for challenge in challenges:
        challenge.is_solved = challenge.id in solved_ids
        challenge_list.append(challenge)

    # Group by category
    challenges_by_category = defaultdict(list)
    for challenge in challenge_list:
        challenges_by_category[challenge.category].append(challenge)

    from ctf.enums import ChallengeCategory

    context = {
        "participant": participant,
        "event": event,
        "challenges": challenge_list,
        "challenges_by_category": dict(challenges_by_category),
        "category_filter": category_filter,
        "categories": ChallengeCategory,
        "solved_ids": solved_ids,
    }
    return render(request, "ctf/participant/challenges.html", context)


@login_required
@ctf_participant_required
def challenge_detail(request: HttpRequest, challenge_id: UUID) -> HttpResponse:
    """Participant challenge detail with submission form.

    Args:
        challenge_id: UUID of the challenge.
    """
    from django.http import Http404

    from ctf.exceptions import CTFNotFoundError
    from ctf.services.challenge import get_challenge
    from ctf.services.participant import get_participant_by_user
    from ctf.services.submission import get_participant_submissions

    participant = get_participant_by_user(request.user)
    if not participant:
        return render(request, "ctf/participant/challenge_detail.html", {})

    try:
        challenge = get_challenge(challenge_id)
    except CTFNotFoundError:
        raise Http404("Challenge not found") from None

    # Validate challenge belongs to participant's event
    if challenge.event_id != participant.event_id:
        return HttpResponse("Forbidden", status=403)

    # Get participant's submissions for this challenge
    submissions = get_participant_submissions(participant.id, challenge_id=challenge_id)
    is_solved = submissions.filter(is_correct=True).exists()
    attempt_count = submissions.count()
    hint_used = submissions.filter(hint_used=True).exists()

    context = {
        "participant": participant,
        "challenge": challenge,
        "event": participant.event,
        "submissions": submissions,
        "is_solved": is_solved,
        "attempt_count": attempt_count,
        "hint_used": hint_used,
        "max_attempts": challenge.max_attempts,
        "attempts_remaining": (challenge.max_attempts - attempt_count) if challenge.max_attempts else None,
    }
    return render(request, "ctf/participant/challenge_detail.html", context)


@login_required
@ctf_participant_required
def participant_range(request: HttpRequest) -> HttpResponse:
    """Participant range status and access.

    Shows range provisioning status and access URLs.
    """
    from ctf.services.participant import get_participant_by_user

    participant = get_participant_by_user(request.user)
    if not participant:
        return render(request, "ctf/participant/range.html", {})

    context = {
        "participant": participant,
        "event": participant.event,
        "range_instance_id": participant.range_instance_id,
        "range_status": participant.range_status,
    }
    return render(request, "ctf/participant/range.html", context)


@login_required
@ctf_participant_required
def scoreboard(request: HttpRequest) -> HttpResponse:
    """Public scoreboard view.

    Shows rankings for current event.
    """
    from ctf.services.participant import get_participant_by_user
    from ctf.services.scoring import get_scoreboard, get_team_scoreboard

    participant = get_participant_by_user(request.user)
    if not participant:
        return render(request, "ctf/participant/scoreboard.html", {})

    event = participant.event

    rankings = get_team_scoreboard(event.id) if event.team_mode else get_scoreboard(event.id)

    context = {
        "participant": participant,
        "event": event,
        "rankings": rankings,
        "team_mode": event.team_mode,
    }
    return render(request, "ctf/participant/scoreboard.html", context)


@login_required
@ctf_participant_required
def participant_team(request: HttpRequest) -> HttpResponse:
    """Participant team view.

    Shows team members and team-specific information.
    """
    from ctf.services.participant import get_participant_by_user

    participant = get_participant_by_user(request.user)
    if not participant:
        return render(request, "ctf/participant/team.html", {})

    team = participant.team
    members = []
    team_score = 0

    if team:
        members = list(team.members.select_related("user"))
        team_score = team.total_score

    context = {
        "participant": participant,
        "event": participant.event,
        "team": team,
        "members": members,
        "team_score": team_score,
    }
    return render(request, "ctf/participant/team.html", context)


@login_required
@ctf_participant_required
@require_http_methods(["GET", "POST"])
def team_join(request: HttpRequest) -> HttpResponse:
    """Join a team using invite code.

    GET: Show join form.
    POST: Process join request.
    """
    from django.shortcuts import redirect

    from ctf.models import CTFTeam
    from ctf.services.participant import get_participant_by_user

    participant = get_participant_by_user(request.user)
    if not participant:
        return render(request, "ctf/participant/team_join.html", {})

    event = participant.event
    error = None

    if request.method == "POST":
        invite_code = request.POST.get("invite_code", "").strip()
        if not invite_code:
            error = "Invite code is required."
        else:
            team = CTFTeam.objects.filter(event=event, invite_code=invite_code).first()
            if not team:
                error = "Invalid invite code."
            elif team.is_full:
                error = "This team is full."
            elif participant.team_id == team.id:
                error = "You are already on this team."
            else:
                participant.team = team
                participant.save(update_fields=["team", "updated_at"])
                logger.info(
                    "Participant %s joined team %s in event %s",
                    participant.id,
                    team.id,
                    event.id,
                )
                return redirect("ctf:participant_team")

    context = {
        "participant": participant,
        "event": event,
        "error": error,
    }
    return render(request, "ctf/participant/team_join.html", context)


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
    from ctf.services import get_organizer_events

    # Get all events first for counting
    all_events = get_organizer_events(request.user)

    # Get stats for active/upcoming/draft events
    from ctf.enums import EventStatus

    active_count = all_events.filter(status=EventStatus.ACTIVE.value).count()
    upcoming_count = all_events.filter(status=EventStatus.SCHEDULED.value).count()
    draft_count = all_events.filter(status=EventStatus.DRAFT.value).count()

    # Get recent 5 events for display
    recent_events = list(all_events[:5])

    context = {
        "recent_events": recent_events,
        "active_count": active_count,
        "upcoming_count": upcoming_count,
        "draft_count": draft_count,
        "total_events": all_events.count(),
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
    events = get_organizer_events(request.user, status=status_filter)

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
@require_http_methods(["GET", "POST"])
def admin_event_create(request: HttpRequest) -> HttpResponse:
    """Create new CTF event.

    GET: Show creation form.
    POST: Process creation.
    """
    from django.shortcuts import redirect

    from ctf.forms import CTFEventForm

    if request.method == "POST":
        form = CTFEventForm(request.POST)
        if form.is_valid():
            event = form.save(commit=False)
            event.created_by = request.user
            event.save()
            logger.info(
                "User %s created event %s: %s",
                request.user.email,
                event.pk,
                event.name,
            )
            return redirect("ctf:admin_event_detail", event_id=event.pk)
    else:
        form = CTFEventForm()

    context = {
        "form": form,
        "is_edit": False,
    }

    return render(request, "ctf/admin/event_form.html", context)


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
        cancel_event,
        complete_event,
        get_event,
        get_event_stats,
        schedule_event,
    )

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        raise Http404("Event not found") from None

    # Check permission - organizers can only access their own events
    if event.created_by_id != request.user.pk:
        return HttpResponse("Forbidden: You do not have access to this event", status=403)

    # Handle status change POST
    if request.method == "POST":
        status_form = EventStatusForm(request.POST, event=event)
        if status_form.is_valid():
            action = status_form.cleaned_data["action"]
            success = False

            if action == "schedule":
                success = schedule_event(event)
            elif action == "activate":
                success = activate_event(event)
            elif action == "complete":
                success = complete_event(event)
            elif action == "cancel":
                success = cancel_event(event)

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


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def admin_event_edit(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Edit CTF event.

    Args:
        event_id: UUID of the event.
    """
    from django.http import Http404
    from django.shortcuts import redirect

    from ctf.exceptions import CTFNotFoundError
    from ctf.forms import CTFEventForm
    from ctf.services import get_event

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        raise Http404("Event not found") from None

    # Check permission - organizers can only access their own events
    if event.created_by_id != request.user.pk:
        return HttpResponse("Forbidden: You do not have access to this event", status=403)

    # Check if event is modifiable
    if not event.is_modifiable:
        logger.warning(
            "User %s attempted to edit non-modifiable event %s",
            request.user.email,
            event.pk,
        )
        return redirect("ctf:admin_event_detail", event_id=event.pk)

    if request.method == "POST":
        form = CTFEventForm(request.POST, instance=event)
        if form.is_valid():
            form.save()
            logger.info(
                "User %s updated event %s: %s",
                request.user.email,
                event.pk,
                event.name,
            )
            return redirect("ctf:admin_event_detail", event_id=event.pk)
    else:
        form = CTFEventForm(instance=event)

    context = {
        "form": form,
        "event": event,
        "is_edit": True,
    }

    return render(request, "ctf/admin/event_form.html", context)


@login_required
@ctf_organizer_required
def admin_challenge_list(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Challenge list for an event.

    Shows all challenges for the event with category grouping.

    Args:
        event_id: UUID of the event.
    """
    from django.http import Http404

    from ctf.exceptions import CTFNotFoundError
    from ctf.services import get_event, list_challenges_for_event

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        raise Http404("Event not found") from None

    # Check permission
    if event.created_by_id != request.user.pk:
        return HttpResponse("Forbidden: You do not have access to this event", status=403)

    challenges = list_challenges_for_event(event_id)

    # Group challenges by category
    from collections import defaultdict

    challenges_by_category = defaultdict(list)
    for challenge in challenges:
        challenges_by_category[challenge.category].append(challenge)

    # Calculate stats
    total_points = sum(c.points for c in challenges)

    context = {
        "event": event,
        "challenges": challenges,
        "challenges_by_category": dict(challenges_by_category),
        "total_points": total_points,
    }

    return render(request, "ctf/admin/challenge_list.html", context)


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def admin_challenge_create(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Create new challenge.

    GET: Show creation form.
    POST: Process creation.

    Args:
        event_id: UUID of the event.
    """
    from django.http import Http404
    from django.shortcuts import redirect

    from ctf.exceptions import CTFNotFoundError
    from ctf.forms import CTFChallengeForm
    from ctf.services import get_event

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        raise Http404("Event not found") from None

    # Check permission
    if event.created_by_id != request.user.pk:
        return HttpResponse("Forbidden: You do not have access to this event", status=403)

    # Check if event content is modifiable (challenges can't be changed in active/terminal events)
    if not event.is_content_modifiable:
        logger.warning(
            "User %s attempted to add challenge to non-modifiable event %s",
            request.user.email,
            event.pk,
        )
        return redirect("ctf:admin_challenge_list", event_id=event.pk)

    if request.method == "POST":
        form = CTFChallengeForm(request.POST, event=event)
        if form.is_valid():
            challenge = form.save()
            logger.info(
                "User %s created challenge %s: %s for event %s",
                request.user.email,
                challenge.pk,
                challenge.name,
                event.pk,
            )
            return redirect("ctf:admin_challenge_detail", challenge_id=challenge.pk)
    else:
        form = CTFChallengeForm(event=event)

    context = {
        "form": form,
        "event": event,
        "is_edit": False,
    }

    return render(request, "ctf/admin/challenge_form.html", context)


@login_required
@ctf_organizer_required
def admin_challenge_detail(request: HttpRequest, challenge_id: UUID) -> HttpResponse:
    """Challenge detail view.

    Shows challenge information, solve statistics, and recent submissions.

    Args:
        challenge_id: UUID of the challenge.
    """
    from django.http import Http404

    from ctf.exceptions import CTFNotFoundError
    from ctf.services import get_challenge

    try:
        challenge = get_challenge(challenge_id)
    except CTFNotFoundError:
        raise Http404("Challenge not found") from None

    # Check permission
    if challenge.event.created_by_id != request.user.pk:
        return HttpResponse("Forbidden: You do not have access to this challenge", status=403)

    # Get submission stats
    from ctf.models import CTFSubmission

    submissions = CTFSubmission.objects.filter(challenge=challenge).order_by("-submitted_at")
    total_submissions = submissions.count()
    correct_submissions = submissions.filter(is_correct=True).count()
    recent_submissions = submissions[:10]

    # Get first blood if any
    first_blood = challenge.first_blood

    context = {
        "challenge": challenge,
        "event": challenge.event,
        "total_submissions": total_submissions,
        "correct_submissions": correct_submissions,
        "recent_submissions": recent_submissions,
        "first_blood": first_blood,
    }

    return render(request, "ctf/admin/challenge_detail.html", context)


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def admin_challenge_edit(request: HttpRequest, challenge_id: UUID) -> HttpResponse:
    """Edit challenge.

    GET: Show edit form.
    POST: Process update.

    Args:
        challenge_id: UUID of the challenge.
    """
    from django.http import Http404
    from django.shortcuts import redirect

    from ctf.exceptions import CTFNotFoundError
    from ctf.forms import CTFChallengeForm
    from ctf.services import get_challenge

    try:
        challenge = get_challenge(challenge_id)
    except CTFNotFoundError:
        raise Http404("Challenge not found") from None

    event = challenge.event

    # Check permission
    if event.created_by_id != request.user.pk:
        return HttpResponse("Forbidden: You do not have access to this challenge", status=403)

    # Check if event content is modifiable
    if not event.is_content_modifiable:
        logger.warning(
            "User %s attempted to edit challenge %s in non-modifiable event %s",
            request.user.email,
            challenge.pk,
            event.pk,
        )
        return redirect("ctf:admin_challenge_detail", challenge_id=challenge.pk)

    if request.method == "POST":
        form = CTFChallengeForm(request.POST, instance=challenge, event=event)
        if form.is_valid():
            form.save()
            logger.info(
                "User %s updated challenge %s: %s",
                request.user.email,
                challenge.pk,
                challenge.name,
            )
            return redirect("ctf:admin_challenge_detail", challenge_id=challenge.pk)
    else:
        form = CTFChallengeForm(instance=challenge, event=event)

    context = {
        "form": form,
        "event": event,
        "challenge": challenge,
        "is_edit": True,
    }

    return render(request, "ctf/admin/challenge_form.html", context)


@login_required
@ctf_organizer_required
def admin_participant_list(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Participant list for an event.

    Shows all participants with filtering by status and statistics.

    Args:
        event_id: UUID of the event.
    """
    from django.http import Http404

    from ctf.enums import ParticipantStatus
    from ctf.exceptions import CTFNotFoundError
    from ctf.services import get_event, list_participants_for_event

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        raise Http404("Event not found") from None

    # Check permission - organizers can only access their own events
    if event.created_by_id != request.user.pk:
        return HttpResponse("Forbidden: You do not have access to this event", status=403)

    # Get participants with optional status filter
    participants = list_participants_for_event(event_id)
    status_filter = request.GET.get("status")

    if status_filter:
        participants = participants.filter(status=status_filter)

    # Calculate statistics
    all_participants = list_participants_for_event(event_id)
    total_count = all_participants.count()
    invited_count = all_participants.filter(status=ParticipantStatus.INVITED.value).count()
    registered_count = all_participants.filter(
        status__in=[
            ParticipantStatus.REGISTERED.value,
            ParticipantStatus.ACTIVE.value,
            ParticipantStatus.COMPLETED.value,
        ]
    ).count()

    # Get status choices for filter dropdown
    status_choices = ParticipantStatus.choices()

    context = {
        "event": event,
        "participants": participants,
        "status_filter": status_filter,
        "status_choices": status_choices,
        "total_count": total_count,
        "invited_count": invited_count,
        "registered_count": registered_count,
    }

    return render(request, "ctf/admin/participant_list.html", context)


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def admin_participant_import(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Import participants from CSV.

    GET: Show import form.
    POST: Process CSV file and create participants.

    Args:
        event_id: UUID of the event.
    """
    from django.contrib import messages
    from django.http import Http404
    from django.shortcuts import redirect

    from ctf.exceptions import CTFNotFoundError, CTFValidationError
    from ctf.forms import CTFParticipantImportForm
    from ctf.services import bulk_import_participants, get_event

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        raise Http404("Event not found") from None

    # Check permission
    if event.created_by_id != request.user.pk:
        return HttpResponse("Forbidden: You do not have access to this event", status=403)

    errors = None
    imported_count = 0

    if request.method == "POST":
        form = CTFParticipantImportForm(request.POST, request.FILES)
        if form.is_valid():
            csv_file = request.FILES["csv_file"]
            try:
                csv_content = csv_file.read().decode("utf-8")
                participants = bulk_import_participants(event_id, csv_content)
                imported_count = len(participants)
                logger.info(
                    "User %s imported %d participants to event %s",
                    request.user.email,
                    imported_count,
                    event_id,
                )
                messages.success(request, f"Successfully imported {imported_count} participants.")
                return redirect("ctf:admin_participant_list", event_id=event_id)
            except CTFValidationError as e:
                errors = e.details.get("errors") or e.details.get("existing") or [str(e)]
                if e.details.get("duplicates"):
                    errors = [f"Duplicate emails: {', '.join(e.details['duplicates'])}"]
                if e.details.get("existing"):
                    errors = [f"Already exists: {', '.join(e.details['existing'])}"]
    else:
        form = CTFParticipantImportForm()

    context = {
        "event": event,
        "form": form,
        "errors": errors,
        "imported_count": imported_count,
    }

    return render(request, "ctf/admin/participant_import.html", context)


@login_required
@ctf_organizer_required
def admin_participant_detail(request: HttpRequest, participant_id: UUID) -> HttpResponse:
    """Participant detail view.

    Shows participant profile, submission history, and actions.

    Args:
        participant_id: UUID of the participant.
    """
    from django.http import Http404

    from ctf.exceptions import CTFNotFoundError
    from ctf.models import CTFSubmission
    from ctf.services import get_participant

    try:
        participant = get_participant(participant_id)
    except CTFNotFoundError:
        raise Http404("Participant not found") from None

    # Check permission - organizers can only access their own events' participants
    if participant.event.created_by_id != request.user.pk:
        return HttpResponse("Forbidden: You do not have access to this participant", status=403)

    # Get submission history
    submissions = (
        CTFSubmission.objects.filter(participant=participant).select_related("challenge").order_by("-submitted_at")
    )

    # Calculate statistics
    total_score = participant.total_score
    solved_count = submissions.filter(is_correct=True).count()
    total_attempts = submissions.count()

    context = {
        "participant": participant,
        "event": participant.event,
        "submissions": submissions,
        "total_score": total_score,
        "solved_count": solved_count,
        "total_attempts": total_attempts,
    }

    return render(request, "ctf/admin/participant_detail.html", context)


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def admin_participant_add(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Add a single participant to an event.

    GET: Show add participant form.
    POST: Create participant and optionally send invite.

    Args:
        event_id: UUID of the event.
    """
    from django.contrib import messages
    from django.http import Http404
    from django.shortcuts import redirect

    from ctf.exceptions import CTFNotFoundError, CTFValidationError
    from ctf.forms import CTFParticipantForm
    from ctf.services import get_event, invite_participant

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        raise Http404("Event not found") from None

    # Check permission
    if event.created_by_id != request.user.pk:
        return HttpResponse("Forbidden: You do not have access to this event", status=403)

    if request.method == "POST":
        form = CTFParticipantForm(request.POST, event=event)
        if form.is_valid():
            try:
                participant = invite_participant(
                    event_id=event_id,
                    email=form.cleaned_data["email"],
                    name=form.cleaned_data["name"],
                )
                logger.info(
                    "User %s added participant %s to event %s",
                    request.user.email,
                    participant.email,
                    event_id,
                )
                messages.success(request, f"Participant {participant.name} added successfully.")
                return redirect("ctf:admin_participant_list", event_id=event_id)
            except CTFValidationError as e:
                form.add_error(None, str(e))
    else:
        form = CTFParticipantForm(event=event)

    context = {
        "event": event,
        "form": form,
        "is_add": True,
    }

    return render(request, "ctf/admin/participant_form.html", context)


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
    return JsonResponse({"placeholder": True, "event_id": str(event_id), "method": request.method})


@login_required
@require_http_methods(["GET", "POST"])
def api_challenge_list(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """API: List challenges or create new challenge.

    Args:
        event_id: UUID of the event.
    """
    # TODO: Implement challenge list/create API
    return JsonResponse({"placeholder": True, "event_id": str(event_id), "method": request.method})


@login_required
@require_http_methods(["GET", "PUT", "DELETE"])
def api_challenge_detail(request: HttpRequest, challenge_id: UUID) -> JsonResponse:
    """API: Get, update, or delete challenge.

    Args:
        challenge_id: UUID of the challenge.
    """
    # TODO: Implement challenge detail API
    return JsonResponse({"placeholder": True, "challenge_id": str(challenge_id), "method": request.method})


@login_required
@require_POST
def api_submit_flag(request: HttpRequest, challenge_id: UUID) -> JsonResponse:
    """API: Submit flag for a challenge.

    Args:
        challenge_id: UUID of the challenge.
    """
    import json

    from ctf.exceptions import CTFNotFoundError, CTFRateLimitError, CTFStateError, CTFValidationError
    from ctf.services.participant import get_participant_by_user
    from ctf.services.scoring import calculate_score, get_participant_rank
    from ctf.services.submission import submit_flag

    participant = get_participant_by_user(request.user)
    if not participant:
        return JsonResponse({"error": "Participant not found"}, status=404)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    flag = body.get("flag", "").strip()
    if not flag:
        return JsonResponse({"error": "Flag is required"}, status=400)

    ip_address = _get_client_ip(request)

    try:
        submission = submit_flag(participant.id, challenge_id, flag, ip_address=ip_address)
        score = calculate_score(participant.id)
        rank = get_participant_rank(participant.id)

        return JsonResponse(
            {
                "correct": submission.is_correct,
                "points_awarded": submission.points_awarded,
                "attempt_number": submission.attempt_number,
                "score": score,
                "rank": rank,
                "message": "Correct!" if submission.is_correct else "Incorrect flag.",
            }
        )
    except CTFNotFoundError as e:
        return JsonResponse({"error": str(e)}, status=404)
    except CTFValidationError as e:
        return JsonResponse({"error": str(e)}, status=400)
    except CTFRateLimitError as e:
        return JsonResponse({"error": str(e)}, status=429)
    except CTFStateError as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
@require_POST
def api_use_hint(request: HttpRequest, challenge_id: UUID) -> JsonResponse:
    """API: Use hint for a challenge.

    Args:
        challenge_id: UUID of the challenge.
    """
    from ctf.exceptions import CTFNotFoundError, CTFValidationError
    from ctf.services.challenge import get_challenge
    from ctf.services.participant import get_participant_by_user
    from ctf.services.submission import use_hint

    participant = get_participant_by_user(request.user)
    if not participant:
        return JsonResponse({"error": "Participant not found"}, status=404)

    try:
        hint_text = use_hint(participant.id, challenge_id)
        challenge = get_challenge(challenge_id)
        return JsonResponse(
            {
                "hint": hint_text,
                "penalty": challenge.hint_penalty,
            }
        )
    except CTFNotFoundError as e:
        return JsonResponse({"error": str(e)}, status=404)
    except CTFValidationError as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
@require_GET
def api_submissions(request: HttpRequest) -> JsonResponse:
    """API: Get submissions for current user."""
    from ctf.services.participant import get_participant_by_user
    from ctf.services.submission import get_participant_submissions

    participant = get_participant_by_user(request.user)
    if not participant:
        return JsonResponse({"error": "Participant not found"}, status=404)

    submissions = get_participant_submissions(participant.id)
    data = [
        {
            "id": str(s.id),
            "challenge_id": str(s.challenge_id),
            "challenge_name": s.challenge.name,
            "is_correct": s.is_correct,
            "points_awarded": s.points_awarded,
            "hint_used": s.hint_used,
            "attempt_number": s.attempt_number,
            "submitted_at": s.submitted_at.isoformat() if s.submitted_at else None,
        }
        for s in submissions.select_related("challenge")
    ]
    return JsonResponse({"submissions": data, "total": len(data)})


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def api_participant_list(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """API: List participants or add new participant.

    GET: Return JSON list of participants.
    POST: Create a new participant.

    Args:
        event_id: UUID of the event.
    """
    import json

    from ctf.exceptions import CTFNotFoundError, CTFValidationError
    from ctf.services import get_event, invite_participant, list_participants_for_event

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        return JsonResponse({"error": "Event not found"}, status=404)

    # Check permission
    if event.created_by_id != request.user.pk:
        return JsonResponse({"error": "Forbidden"}, status=403)

    if request.method == "GET":
        participants = list_participants_for_event(event_id)
        status_filter = request.GET.get("status")
        if status_filter:
            participants = participants.filter(status=status_filter)

        data = [
            {
                "id": str(p.id),
                "name": p.name,
                "email": p.email,
                "status": p.status,
                "team_name": p.team.name if p.team else None,
                "registered_at": p.registered_at.isoformat() if p.registered_at else None,
                "total_score": p.total_score,
            }
            for p in participants
        ]
        return JsonResponse({"participants": data, "total": len(data)})

    elif request.method == "POST":
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        name = body.get("name")
        email = body.get("email")

        if not name or not email:
            return JsonResponse({"error": "name and email are required"}, status=400)

        try:
            participant = invite_participant(event_id, email, name)
            return JsonResponse(
                {
                    "id": str(participant.id),
                    "name": participant.name,
                    "email": participant.email,
                    "status": participant.status,
                    "invite_token": participant.invite_token,
                },
                status=201,
            )
        except CTFValidationError as e:
            return JsonResponse({"error": str(e)}, status=400)

    return JsonResponse({"error": "Method not allowed"}, status=405)


@login_required
@ctf_organizer_required
@require_POST
def api_participant_import(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """API: Bulk import participants from JSON.

    Expects JSON body with "participants" array containing objects with
    "name" and "email" fields.

    Args:
        event_id: UUID of the event.
    """
    import json

    from ctf.exceptions import CTFNotFoundError, CTFValidationError
    from ctf.services import get_event, invite_participant

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        return JsonResponse({"error": "Event not found"}, status=404)

    # Check permission
    if event.created_by_id != request.user.pk:
        return JsonResponse({"error": "Forbidden"}, status=403)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    participants_data = body.get("participants", [])
    if not isinstance(participants_data, list):
        return JsonResponse({"error": "participants must be an array"}, status=400)

    imported = []
    errors = []

    for idx, p_data in enumerate(participants_data):
        name = p_data.get("name")
        email = p_data.get("email")

        if not name or not email:
            errors.append({"index": idx, "error": "name and email are required"})
            continue

        try:
            participant = invite_participant(event_id, email, name)
            imported.append(
                {
                    "id": str(participant.id),
                    "name": participant.name,
                    "email": participant.email,
                }
            )
        except CTFValidationError as e:
            errors.append({"index": idx, "email": email, "error": str(e)})

    return JsonResponse(
        {
            "imported": len(imported),
            "participants": imported,
            "errors": errors,
        }
    )


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "DELETE"])
def api_participant_detail(request: HttpRequest, participant_id: UUID) -> JsonResponse:
    """API: Get or remove participant.

    GET: Return participant details as JSON.
    DELETE: Soft-delete the participant.

    Args:
        participant_id: UUID of the participant.
    """
    from ctf.exceptions import CTFNotFoundError
    from ctf.models import CTFSubmission
    from ctf.services import delete_participant, get_participant

    try:
        participant = get_participant(participant_id)
    except CTFNotFoundError:
        return JsonResponse({"error": "Participant not found"}, status=404)

    # Check permission
    if participant.event.created_by_id != request.user.pk:
        return JsonResponse({"error": "Forbidden"}, status=403)

    if request.method == "GET":
        # Get submission stats
        submissions = CTFSubmission.objects.filter(participant=participant)
        correct_submissions = submissions.filter(is_correct=True)

        return JsonResponse(
            {
                "id": str(participant.id),
                "name": participant.name,
                "email": participant.email,
                "status": participant.status,
                "team_name": participant.team.name if participant.team else None,
                "registered_at": participant.registered_at.isoformat() if participant.registered_at else None,
                "invited_at": participant.invited_at.isoformat() if participant.invited_at else None,
                "last_active_at": participant.last_active_at.isoformat() if participant.last_active_at else None,
                "total_score": participant.total_score,
                "solved_count": correct_submissions.count(),
                "attempt_count": submissions.count(),
                "event_id": str(participant.event_id),
            }
        )

    elif request.method == "DELETE":
        try:
            delete_participant(participant_id)
            return JsonResponse({"deleted": True, "id": str(participant_id)})
        except CTFNotFoundError:
            return JsonResponse({"error": "Participant not found"}, status=404)

    return JsonResponse({"error": "Method not allowed"}, status=405)


@login_required
@ctf_organizer_required
@require_POST
def api_participant_resend_invite(request: HttpRequest, participant_id: UUID) -> JsonResponse:
    """API: Resend invitation to a participant.

    Regenerates the invite token and updates expiry.

    Args:
        participant_id: UUID of the participant.
    """
    from ctf.exceptions import CTFNotFoundError, CTFStateError
    from ctf.services import get_participant, resend_invite

    try:
        participant = get_participant(participant_id)
    except CTFNotFoundError:
        return JsonResponse({"error": "Participant not found"}, status=404)

    # Check permission
    if participant.event.created_by_id != request.user.pk:
        return JsonResponse({"error": "Forbidden"}, status=403)

    try:
        updated = resend_invite(participant_id)
        return JsonResponse(
            {
                "success": True,
                "id": str(updated.id),
                "invite_token": updated.invite_token,
                "invite_token_expires": updated.invite_token_expires.isoformat(),
            }
        )
    except CTFStateError as e:
        return JsonResponse({"error": str(e)}, status=400)


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
    from ctf.exceptions import CTFNotFoundError
    from ctf.services import get_event
    from ctf.services.scoring import get_scoreboard, get_team_scoreboard

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        return JsonResponse({"error": "Event not found"}, status=404)

    rankings = get_team_scoreboard(event.id) if event.team_mode else get_scoreboard(event.id)

    return JsonResponse(
        {
            "event_id": str(event.id),
            "team_mode": event.team_mode,
            "rankings": rankings,
        }
    )


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def api_notification_list(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """API: List or create notifications.

    Args:
        event_id: UUID of the event.
    """
    # TODO: Implement notification list/create API
    return JsonResponse({"placeholder": True, "event_id": str(event_id), "method": request.method})


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
