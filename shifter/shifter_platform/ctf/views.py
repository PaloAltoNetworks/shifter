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
import json
import logging
from typing import TYPE_CHECKING, cast
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from ctf.bridges import get_user_role

if TYPE_CHECKING:
    from django.http import HttpRequest

logger = logging.getLogger(__name__)


def _get_user(request: HttpRequest) -> User:
    """Get authenticated user from request. Use only in @login_required views."""
    assert request.user.is_authenticated, "View must use @login_required"
    return cast(User, request.user)


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
        user = _get_user(request)
        role = get_user_role(user)
        if not role.is_ctf_organizer:
            logger.warning(
                "CTF organizer access denied for user %s",
                user.email,
            )
            return HttpResponse("Forbidden: CTF organizer access required", status=403)
        return view_func(request, *args, **kwargs)

    return wrapper


def ctf_participant_required(view_func):
    """Decorator that requires the user to be a registered CTF participant.

    Checks the CTFParticipant table directly — works regardless of
    UserProfile.user_type, so organizers and standard users who are
    also participants aren't blocked.
    """

    @functools.wraps(view_func)
    def wrapper(request: HttpRequest, *args, **kwargs):
        from ctf.models import CTFParticipant

        user = _get_user(request)
        has_participation = CTFParticipant.objects.filter(
            user=user,
            registered_at__isnull=False,
        ).exists()
        if not has_participation:
            logger.warning(
                "CTF participant access denied for user %s",
                user.email,
            )
            return HttpResponse("Forbidden: CTF participant access required", status=403)
        return view_func(request, *args, **kwargs)

    return wrapper


def ctf_role_required(view_func):
    """Decorator that requires the user to be a CTF organizer or participant.

    Returns 403 Forbidden if user has no CTF role.
    Must be used after @login_required.
    """

    @functools.wraps(view_func)
    def wrapper(request: HttpRequest, *args, **kwargs):
        user = _get_user(request)
        role = get_user_role(user)
        if not role.is_ctf_organizer and not role.is_ctf_participant:
            logger.warning(
                "CTF access denied for user %s (no CTF role)",
                user.email,
            )
            return HttpResponse("Forbidden: CTF access required", status=403)
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


def _check_event_ownership(event, user) -> JsonResponse | None:
    """Return a 403 JsonResponse if the user does not own the event, else None."""
    if event.created_by_id != user.pk:
        return JsonResponse({"error": "Forbidden"}, status=403)
    return None


# -----------------------------------------------------------------------------
# Participant Views (CTF Competitors)
# -----------------------------------------------------------------------------


def ctf_register(request: HttpRequest) -> HttpResponse:
    """Authenticate a participant via magic link token.

    No login required. The invite token IS the authentication.
    Participants are auto-registered at add-time via _auto_register_participant(),
    so every valid token maps to a participant with a linked Django user.
    """
    from django.contrib.auth import login

    from ctf.models import CTFParticipant

    token = request.GET.get("token")
    if not token:
        return HttpResponse("Missing invite token.", status=400)

    participant = CTFParticipant.objects.filter(invite_token=token).select_related("user").first()
    if not participant or not participant.user:
        return HttpResponse("Invalid invite token.", status=400)

    login(request, participant.user, backend="django.contrib.auth.backends.ModelBackend")
    return redirect("mission_control:dashboard")


@login_required
@ctf_participant_required
def participant_dashboard(request: HttpRequest) -> HttpResponse:
    """Participant main dashboard.

    Shows event overview, challenge progress, and quick links.
    """
    from ctf.services.challenge import get_available_challenges
    from ctf.services.participant import get_participant_by_user
    from ctf.services.scoring import calculate_score, get_participant_rank

    participant = get_participant_by_user(_get_user(request))
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

    participant = get_participant_by_user(_get_user(request))
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

    participant = get_participant_by_user(_get_user(request))
    if not participant:
        return render(request, "ctf/participant/challenges.html", {})

    event = participant.event
    challenges = get_available_challenges(event.id)

    # Apply category filter if provided
    category_filter = request.GET.get("category")
    if category_filter:
        challenges = challenges.filter(category=category_filter)

    # Apply tag filter if provided
    tag_filter = request.GET.get("tag")
    if tag_filter:
        challenges = challenges.filter(tags__name=tag_filter).distinct()

    # Build set of solved challenge IDs
    correct_submissions = get_participant_submissions(participant.id).filter(is_correct=True)
    solved_ids = set(correct_submissions.values_list("challenge_id", flat=True))

    # Build prerequisite info: which challenges have unmet prerequisites
    from ctf.models import CTFChallengePrerequisite

    all_prereqs = CTFChallengePrerequisite.objects.filter(
        challenge__event_id=event.id,
    ).select_related("required_challenge")

    # Map challenge_id -> list of required challenge names
    prereqs_by_challenge: dict = defaultdict(list)
    locked_ids: set = set()
    for p in all_prereqs:
        prereqs_by_challenge[p.challenge_id].append(p.required_challenge)
        if p.required_challenge_id not in solved_ids:
            locked_ids.add(p.challenge_id)

    # Annotate challenges with solve status and lock status
    challenge_list = []
    for challenge in challenges:
        challenge.is_solved = challenge.id in solved_ids  # type: ignore[attr-defined]
        challenge.is_locked = challenge.id in locked_ids  # type: ignore[attr-defined]
        challenge.required_challenges = prereqs_by_challenge.get(challenge.id, [])  # type: ignore[attr-defined]
        challenge_list.append(challenge)

    # Group by category
    challenges_by_category = defaultdict(list)
    for challenge in challenge_list:
        challenges_by_category[challenge.category].append(challenge)

    from ctf.enums import ChallengeCategory
    from ctf.models import CTFChallengeTag

    # Get all tags used by challenges in this event
    event_tags = (
        CTFChallengeTag.objects.filter(
            event=event,
            challenges__isnull=False,
        )
        .distinct()
        .order_by("name")
    )

    context = {
        "participant": participant,
        "event": event,
        "challenges": challenge_list,
        "challenges_by_category": dict(challenges_by_category),
        "category_filter": category_filter,
        "tag_filter": tag_filter,
        "categories": ChallengeCategory,
        "event_tags": event_tags,
        "solved_ids": solved_ids,
        "locked_ids": locked_ids,
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

    participant = get_participant_by_user(_get_user(request))
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

    # Get challenge files
    from ctf.services.attachment import get_challenge_files

    challenge_files = get_challenge_files(challenge_id)

    # Check prerequisites
    from ctf.services.challenge import check_prerequisites_met

    prereqs_met, unmet_challenges = check_prerequisites_met(challenge_id, participant.id)

    # Calculate timeout state for attempt limits
    attempt_limit_mode = participant.event.attempt_limit_mode
    timeout_retry_after = None
    if attempt_limit_mode == "timeout" and challenge.max_attempts > 0:
        from ctf.services.submission import _count_attempts_in_current_window

        attempt_cooldown = participant.event.attempt_limit_cooldown_seconds
        attempt_count = _count_attempts_in_current_window(submissions, attempt_cooldown)
        if attempt_count >= challenge.max_attempts:
            last_sub = submissions.first()
            if last_sub:
                elapsed = (timezone.now() - last_sub.submitted_at).total_seconds()
                if elapsed < attempt_cooldown:
                    timeout_retry_after = int(attempt_cooldown - elapsed) + 1

    attempts_remaining = None
    if challenge.max_attempts:
        attempts_remaining = max(0, challenge.max_attempts - attempt_count)

    context = {
        "participant": participant,
        "challenge": challenge,
        "event": participant.event,
        "submissions": submissions,
        "is_solved": is_solved,
        "attempt_count": attempt_count,
        "hint_used": hint_used,
        "max_attempts": challenge.max_attempts,
        "attempts_remaining": attempts_remaining,
        "challenge_files": challenge_files,
        "prereqs_met": prereqs_met,
        "unmet_challenges": unmet_challenges,
        "attempt_limit_mode": attempt_limit_mode,
        "timeout_retry_after": timeout_retry_after,
    }
    return render(request, "ctf/participant/challenge_detail.html", context)


@login_required
@ctf_participant_required
def participant_range(request: HttpRequest) -> HttpResponse:
    """Participant range status and access.

    Shows range provisioning status and access URLs.
    """
    from ctf.services.participant import get_participant_by_user

    participant = get_participant_by_user(_get_user(request))
    if not participant:
        return render(request, "ctf/participant/range.html", {})

    # Look up provisioned instances (with IPs) via CMS services
    target_instances = []
    if participant.range_instance_id and participant.range_status == "ready" and participant.user:
        import cms.services as cms_services

        target_instances = cms_services.get_range_target_instances(participant.user.pk)

    context = {
        "participant": participant,
        "event": participant.event,
        "range_instance_id": participant.range_instance_id,
        "range_status": participant.range_status,
        "target_instances": target_instances,
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

    participant = get_participant_by_user(_get_user(request))
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

    participant = get_participant_by_user(_get_user(request))
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

    participant = get_participant_by_user(_get_user(request))
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
    return render(request, "ctf/help.html")


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
    all_events = get_organizer_events(_get_user(request))

    # Get stats for active/upcoming/draft events
    from ctf.enums import EventStatus

    active_count = all_events.filter(status=EventStatus.ACTIVE.value).count()
    upcoming_count = all_events.filter(status=EventStatus.REGISTRATION.value).count()
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
    scenarios_json = json.dumps([{"id": sid, "name": name} for sid, name in scenarios])
    return render(
        request,
        "ctf/admin/event_form.html",
        {
            "is_edit": False,
            "scenarios_json": scenarios_json,
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
            elif action == "pause":
                success = pause_event(event)
            elif action == "resume":
                success = resume_event(event)
            elif action == "complete":
                success = complete_event(event)
            elif action == "archive":
                success = archive_event(event)
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

    user = _get_user(request)
    scenarios = cms_list_scenarios(user)
    scenarios_json = json.dumps([{"id": sid, "name": name} for sid, name in scenarios])
    return render(
        request,
        "ctf/admin/event_form.html",
        {
            "is_edit": True,
            "event_id": str(event_id),
            "scenarios_json": scenarios_json,
        },
    )


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
    from ctf.models import CTFChallenge, CTFSubmission

    submissions = CTFSubmission.objects.filter(challenge=challenge).order_by("-submitted_at")
    total_submissions = submissions.count()
    correct_submissions = submissions.filter(is_correct=True).count()
    recent_submissions = submissions[:10]

    # Get first blood if any
    first_blood = challenge.first_blood

    # Get flags for this challenge
    flags = challenge.flags.all()

    # Get files for this challenge
    from ctf.services.attachment import get_challenge_files

    challenge_files = get_challenge_files(challenge_id)

    # Get prerequisites
    from ctf.services.challenge import get_prerequisites

    prerequisites = get_prerequisites(challenge_id)

    # Get other challenges in this event (for prerequisite selector)
    other_challenges = (
        CTFChallenge.objects.filter(
            event=challenge.event,
        )
        .exclude(pk=challenge_id)
        .order_by("category", "name")
    )

    context = {
        "challenge": challenge,
        "event": challenge.event,
        "total_submissions": total_submissions,
        "correct_submissions": correct_submissions,
        "recent_submissions": recent_submissions,
        "first_blood": first_blood,
        "flags": flags,
        "challenge_files": challenge_files,
        "prerequisites": prerequisites,
        "other_challenges": other_challenges,
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
                csv_content = csv_file.read().decode("utf-8")  # type: ignore[union-attr]
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
    from django.http import Http404

    from ctf.exceptions import CTFNotFoundError
    from ctf.services import get_event

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        raise Http404("Event not found") from None

    if event.created_by_id != request.user.pk:
        return HttpResponse("Forbidden: You do not have access to this event", status=403)

    from ctf.models import CTFTeam

    teams = CTFTeam.objects.filter(event=event).select_related("captain").order_by("name")

    return render(
        request,
        "ctf/admin/team_list.html",
        {"event": event, "teams": teams},
    )


@login_required
@ctf_organizer_required
def admin_scoreboard(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Admin scoreboard view with extra details.

    Args:
        event_id: UUID of the event.
    """
    from django.http import Http404

    from ctf.exceptions import CTFNotFoundError
    from ctf.services import get_event

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        raise Http404("Event not found") from None

    if event.created_by_id != request.user.pk:
        return HttpResponse("Forbidden: You do not have access to this event", status=403)

    from ctf.services import get_event_stats, get_scoreboard, get_team_scoreboard

    stats = get_event_stats(event)

    rankings = get_team_scoreboard(event.id) if event.team_mode else get_scoreboard(event.id)

    return render(
        request,
        "ctf/admin/scoreboard.html",
        {
            "event": event,
            "rankings": rankings,
            "team_mode": event.team_mode,
            "stats": stats,
        },
    )


@login_required
@ctf_organizer_required
def admin_range_list(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Range status overview for an event.

    Args:
        event_id: UUID of the event.
    """
    from django.http import Http404

    from ctf.exceptions import CTFNotFoundError
    from ctf.models import CTFParticipant
    from ctf.services import get_event

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        raise Http404("Event not found") from None

    if event.created_by_id != request.user.pk:
        return HttpResponse("Forbidden: You do not have access to this event", status=403)

    participants = CTFParticipant.objects.filter(event=event).order_by("name")

    return render(
        request,
        "ctf/admin/range_list.html",
        {"event": event, "participants": participants},
    )


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


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def admin_notification_create(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Create new notification.

    Args:
        event_id: UUID of the event.
    """
    from django.http import Http404

    from ctf.exceptions import CTFNotFoundError
    from ctf.services import get_event

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        raise Http404("Event not found") from None

    if event.created_by_id != request.user.pk:
        return HttpResponse("Forbidden: You do not have access to this event", status=403)

    if request.method == "POST":
        from ctf.enums import NotificationStatus, NotificationType
        from ctf.models import CTFNotification
        from ctf.services import notification

        subject = request.POST.get("subject", "").strip()
        body = request.POST.get("body", "").strip()
        action = request.POST.get("action", "draft")

        if not subject or not body:
            return render(
                request,
                "ctf/admin/notification_form.html",
                {"event": event, "error": "Subject and body are required."},
            )

        if action == "send_now":
            notif = notification.send_announcement(
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
                    "ctf/admin/notification_form.html",
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

        from django.shortcuts import redirect

        return redirect("ctf:admin_notification_list", event_id=event.id)

    return render(
        request,
        "ctf/admin/notification_form.html",
        {"event": event},
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
        raise Http404("Event not found") from None

    if event.created_by_id != request.user.pk:
        return HttpResponse("Forbidden: You do not have access to this event", status=403)

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
    import json

    from ctf.exceptions import CTFValidationError
    from ctf.services import create_event, get_organizer_events

    user = _get_user(request)

    if request.method == "GET":
        events = get_organizer_events(user)
        data = [
            {
                "id": str(e.id),
                "name": e.name,
                "status": e.status,
                "event_start": e.event_start.isoformat(),
                "event_end": e.event_end.isoformat(),
                "team_mode": e.team_mode,
            }
            for e in events
        ]
        return JsonResponse({"events": data})

    # POST
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    # Parse datetime strings to datetime objects for the service layer
    from django.utils.dateparse import parse_datetime

    for field in ("event_start", "event_end", "registration_deadline"):
        if field in body and isinstance(body[field], str):
            parsed = parse_datetime(body[field])
            if parsed:
                body[field] = parsed

    try:
        event = create_event(user, body)
        return JsonResponse(
            {
                "id": str(event.id),
                "name": event.name,
                "status": event.status,
            },
            status=201,
        )
    except CTFValidationError as e:
        return JsonResponse({"error": str(e)}, status=400)
    except ValidationError as e:
        # Django model validation (from full_clean in save)
        return JsonResponse({"error": "; ".join(e.messages)}, status=400)


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "PUT", "DELETE"])
def api_event_detail(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """API: Get, update, or delete event.

    Args:
        event_id: UUID of the event.
    """
    from ctf.exceptions import CTFNotFoundError
    from ctf.services import get_event

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        return JsonResponse({"error": "Event not found"}, status=404)

    if event.created_by_id != request.user.pk:
        return JsonResponse({"error": "Forbidden"}, status=403)

    from ctf.exceptions import CTFStateError, CTFValidationError
    from ctf.services import delete_event, update_event

    if request.method == "GET":
        return JsonResponse(
            {
                "id": str(event.id),
                "name": event.name,
                "description": event.description,
                "status": event.status,
                "event_start": event.event_start.isoformat(),
                "event_end": event.event_end.isoformat(),
                "registration_deadline": event.registration_deadline.isoformat()
                if event.registration_deadline
                else None,
                "scenario_id": event.scenario_id,
                "auto_cleanup": event.auto_cleanup,
                "cleanup_delay_hours": event.cleanup_delay_hours,
                "max_participants": event.max_participants,
                "team_mode": event.team_mode,
                "team_size_limit": event.team_size_limit,
                "range_config": event.range_config,
                "range_spinup_minutes": event.range_spinup_minutes,
                "submission_cooldown_seconds": event.submission_cooldown_seconds,
                "attempt_limit_mode": event.attempt_limit_mode,
                "attempt_limit_cooldown_seconds": event.attempt_limit_cooldown_seconds,
            }
        )

    if request.method == "DELETE":
        delete_event(event_id)
        return JsonResponse({}, status=204)

    # PUT
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    # Parse datetime strings to datetime objects for the service layer
    from django.utils.dateparse import parse_datetime

    for field in ("event_start", "event_end", "registration_deadline"):
        if field in body and isinstance(body[field], str):
            parsed = parse_datetime(body[field])
            if parsed:
                body[field] = parsed

    try:
        updated = update_event(event_id, body)
        return JsonResponse(
            {
                "id": str(updated.id),
                "name": updated.name,
                "status": updated.status,
            }
        )
    except (CTFValidationError, CTFStateError) as e:
        return JsonResponse({"error": str(e)}, status=400)
    except ValidationError as e:
        return JsonResponse({"error": "; ".join(e.messages)}, status=400)


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def api_challenge_list(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """API: List challenges or create new challenge.

    Args:
        event_id: UUID of the event.
    """
    import json

    from ctf.exceptions import CTFNotFoundError, CTFStateError, CTFValidationError
    from ctf.services import create_challenge, get_event, list_challenges_for_event

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        return JsonResponse({"error": "Event not found"}, status=404)

    forbidden = _check_event_ownership(event, _get_user(request))
    if forbidden:
        return forbidden

    if request.method == "GET":
        challenges = list_challenges_for_event(event_id).prefetch_related("tags")
        data = [
            {
                "id": str(c.id),
                "name": c.name,
                "category": c.category,
                "points": c.points,
                "difficulty": c.difficulty,
                "order": c.order,
                "tags": list(c.tags.values_list("name", flat=True)),
            }
            for c in challenges
        ]
        return JsonResponse({"challenges": data})

    # POST
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    try:
        challenge = create_challenge(event_id, body)
        return JsonResponse(
            {
                "id": str(challenge.id),
                "name": challenge.name,
                "category": challenge.category,
                "points": challenge.points,
            },
            status=201,
        )
    except CTFNotFoundError as e:
        return JsonResponse({"error": str(e)}, status=404)
    except (CTFValidationError, CTFStateError) as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "PUT", "DELETE"])
def api_challenge_detail(request: HttpRequest, challenge_id: UUID) -> JsonResponse:
    """API: Get, update, or delete challenge.

    Args:
        challenge_id: UUID of the challenge.
    """
    import json

    from ctf.exceptions import CTFNotFoundError, CTFStateError, CTFValidationError
    from ctf.services import delete_challenge, get_challenge, update_challenge

    try:
        challenge = get_challenge(challenge_id)
    except CTFNotFoundError:
        return JsonResponse({"error": "Challenge not found"}, status=404)

    forbidden = _check_event_ownership(challenge.event, _get_user(request))
    if forbidden:
        return forbidden

    if request.method == "GET":
        return JsonResponse(
            {
                "id": str(challenge.id),
                "name": challenge.name,
                "description": challenge.description,
                "category": challenge.category,
                "points": challenge.points,
                "difficulty": challenge.difficulty,
                "flag_format": challenge.flag_format,
                "hint": challenge.hint,
                "hint_penalty": challenge.hint_penalty,
                "max_attempts": challenge.max_attempts,
                "order": challenge.order,
                "release_time": challenge.release_time.isoformat() if challenge.release_time else None,
                "tags": list(challenge.tags.values_list("name", flat=True)),
            }
        )

    if request.method == "DELETE":
        try:
            delete_challenge(challenge_id)
            return JsonResponse({}, status=204)
        except (CTFNotFoundError, CTFStateError) as e:
            return JsonResponse({"error": str(e)}, status=400)

    # PUT
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    try:
        updated = update_challenge(challenge_id, body)
        return JsonResponse(
            {
                "id": str(updated.id),
                "name": updated.name,
                "category": updated.category,
                "points": updated.points,
            }
        )
    except (CTFNotFoundError, CTFValidationError, CTFStateError) as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
@ctf_participant_required
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

    participant = get_participant_by_user(_get_user(request))
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
        response = JsonResponse({"error": str(e), "details": e.details}, status=429)
        if e.details.get("retry_after_seconds"):
            response["Retry-After"] = str(e.details["retry_after_seconds"])
        return response
    except CTFStateError as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
@ctf_participant_required
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

    participant = get_participant_by_user(_get_user(request))
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
@ctf_participant_required
@require_GET
def api_submissions(request: HttpRequest) -> JsonResponse:
    """API: Get submissions for current user."""
    from ctf.services.participant import get_participant_by_user
    from ctf.services.submission import get_participant_submissions

    participant = get_participant_by_user(_get_user(request))
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
                    "invited": True,
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
    """API: Resend magic link email to a participant.

    Regenerates the invite token and sends a new email.
    Works for any participant regardless of registration status.

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
                "invited": True,
            }
        )
    except CTFStateError as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
@ctf_participant_required
@require_GET
def api_range_status(request: HttpRequest) -> JsonResponse:
    """API: Get range status for current participant."""
    from ctf.exceptions import CTFNotFoundError
    from ctf.models import CTFParticipant

    # Find participant for current user's active event
    participant = (
        CTFParticipant.objects.filter(
            user=_get_user(request),
        )
        .order_by("-event__event_start")
        .first()
    )

    if not participant:
        return JsonResponse({"status": "not_assigned", "range_instance_id": None})

    from ctf.services import range as range_service

    try:
        status = range_service.get_range_status(participant.pk)
        return JsonResponse(status)
    except CTFNotFoundError:
        return JsonResponse({"error": "Participant not found"}, status=404)


@login_required
@ctf_participant_required
@require_POST
def api_range_access(request: HttpRequest) -> JsonResponse:
    """API: Get range access URL.

    Delegates to mission_control's Guacamole RDP endpoint.
    CTF participants are standard users with ranges — the platform's
    existing RDP access flow works for them directly.
    """
    from django.urls import reverse

    return JsonResponse(
        {
            "redirect": reverse("mission_control:guacamole_rdp_url"),
            "message": "Use the mission_control RDP endpoint directly.",
        }
    )


@login_required
@ctf_role_required
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
    import json

    from ctf.exceptions import CTFNotFoundError
    from ctf.models import CTFNotification
    from ctf.services import get_event

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        return JsonResponse({"error": "Event not found"}, status=404)

    if event.created_by_id != request.user.pk:
        return JsonResponse({"error": "Forbidden"}, status=403)

    if request.method == "POST":
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        from ctf.services import notification

        subject = data.get("subject", "").strip()
        body = data.get("body", "").strip()

        if not subject or not body:
            return JsonResponse({"error": "Subject and body are required"}, status=400)

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

    # GET: list notifications
    notifications = CTFNotification.objects.filter(event=event).order_by("-created_at")
    data = [
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

    return JsonResponse({"notifications": data})


@login_required
@ctf_organizer_required
@require_POST
def api_notification_send(request: HttpRequest, notification_id: UUID) -> HttpResponse:
    """API: Send a notification.

    Args:
        notification_id: UUID of the notification.
    """
    from ctf.enums import NotificationType
    from ctf.models import CTFNotification
    from ctf.services import notification

    notif = CTFNotification.objects.select_related("event").filter(pk=notification_id).first()
    if not notif:
        if "text/html" in request.headers.get("Accept", ""):
            return HttpResponse("Notification not found", status=404)
        return JsonResponse({"error": "Notification not found"}, status=404)

    if notif.event.created_by_id != request.user.pk:
        if "text/html" in request.headers.get("Accept", ""):
            return HttpResponse("Forbidden: You do not have access to this event", status=403)
        return JsonResponse({"error": "Forbidden"}, status=403)

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

    # Browser form submission: redirect back to notification list
    if "text/html" in request.headers.get("Accept", ""):
        from django.shortcuts import redirect

        return redirect("ctf:admin_notification_list", event_id=notif.event_id)

    return JsonResponse(
        {
            "notification_id": str(notification_id),
            "status": "sent",
        }
    )


@login_required
@ctf_organizer_required
@require_GET
def api_range_list(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """API: Range status for all participants in an event.

    Args:
        event_id: UUID of the event.
    """
    from ctf.exceptions import CTFNotFoundError
    from ctf.models import CTFParticipant
    from ctf.services import get_event

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        return JsonResponse({"error": "Event not found"}, status=404)

    if event.created_by_id != request.user.pk:
        return JsonResponse({"error": "Forbidden"}, status=403)

    participants = CTFParticipant.objects.filter(event=event).order_by("name")
    data = [
        {
            "participant_id": str(p.pk),
            "name": p.name,
            "email": p.email,
            "range_instance_id": p.range_instance_id,
            "range_status": p.range_status or "not_assigned",
        }
        for p in participants
    ]

    return JsonResponse({"event_id": str(event_id), "ranges": data})


@login_required
@ctf_organizer_required
@require_POST
def api_provision_ranges(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """API: Trigger bulk range provisioning for an event.

    Args:
        event_id: UUID of the event.
    """
    from ctf.exceptions import CTFNotFoundError
    from ctf.services import get_event

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        return JsonResponse({"error": "Event not found"}, status=404)

    if event.created_by_id != request.user.pk:
        return JsonResponse({"error": "Forbidden"}, status=403)

    from ctf.services import range as range_service

    result = range_service.provision_event_ranges(event_id)
    return JsonResponse(result)


@login_required
@ctf_organizer_required
@require_POST
def api_provision_participant_range(request: HttpRequest, participant_id: UUID) -> JsonResponse:
    """API: Provision a range for a single participant."""
    from ctf.services import range as range_service

    return _participant_range_action(request, participant_id, range_service.provision_participant_range)


@login_required
@ctf_organizer_required
@require_POST
def api_destroy_participant_range(request: HttpRequest, participant_id: UUID) -> JsonResponse:
    """API: Destroy a range for a single participant."""
    from ctf.services import range as range_service

    return _participant_range_action(request, participant_id, range_service.destroy_participant_range)


def _participant_range_action(request: HttpRequest, participant_id: UUID, action_fn) -> JsonResponse:
    """Common logic for organizer range actions (stop, start, restart, etc.)."""
    from ctf.exceptions import CTFNotFoundError, CTFRangeError
    from ctf.models import CTFParticipant

    try:
        participant = CTFParticipant.objects.select_related("event").get(pk=participant_id)
    except CTFParticipant.DoesNotExist:
        return JsonResponse({"error": "Participant not found"}, status=404)

    if participant.event.created_by_id != request.user.pk:
        return JsonResponse({"error": "Forbidden"}, status=403)

    try:
        result = action_fn(participant_id)
        return JsonResponse(result)
    except (CTFNotFoundError, CTFRangeError) as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
@ctf_organizer_required
@require_POST
def api_stop_participant_range(request: HttpRequest, participant_id: UUID) -> JsonResponse:
    """API: Stop (pause) a participant's range."""
    from ctf.services import range as range_service

    return _participant_range_action(request, participant_id, range_service.stop_participant_range)


@login_required
@ctf_organizer_required
@require_POST
def api_start_participant_range(request: HttpRequest, participant_id: UUID) -> JsonResponse:
    """API: Start (resume) a participant's stopped range."""
    from ctf.services import range as range_service

    return _participant_range_action(request, participant_id, range_service.start_participant_range)


@login_required
@ctf_organizer_required
@require_POST
def api_restart_participant_range(request: HttpRequest, participant_id: UUID) -> JsonResponse:
    """API: Restart a participant's range."""
    from ctf.services import range as range_service

    return _participant_range_action(request, participant_id, range_service.restart_participant_range)


@login_required
@ctf_organizer_required
@require_POST
def api_send_invitations(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """API: Send invitation emails to all uninvited participants.

    Args:
        event_id: UUID of the event.
    """
    from ctf.exceptions import CTFNotFoundError
    from ctf.services import get_event
    from ctf.services.notification import send_invitations

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        return JsonResponse({"error": "Event not found"}, status=404)

    if event.created_by_id != request.user.pk:
        return JsonResponse({"error": "Forbidden"}, status=403)

    result = send_invitations(event_id)
    return JsonResponse({"success": True, **result})


@login_required
@ctf_organizer_required
@require_GET
def api_scenarios(request: HttpRequest) -> JsonResponse:
    """API: List available scenarios for CTF events.

    Returns a list of scenario id/name pairs from the CMS registry.
    """
    from ctf.bridges import cms_list_scenarios

    user = _get_user(request)
    scenarios = [{"id": sid, "name": name} for sid, name in cms_list_scenarios(user)]
    return JsonResponse({"scenarios": scenarios})


# -----------------------------------------------------------------------------
# Flag Management API Views
# -----------------------------------------------------------------------------


@login_required
@ctf_organizer_required
@require_POST
def api_add_flag(request: HttpRequest, challenge_id: UUID) -> JsonResponse:
    """API: Add a flag to a challenge.

    Args:
        challenge_id: UUID of the challenge.
    """
    from ctf.exceptions import CTFNotFoundError, CTFStateError, CTFValidationError
    from ctf.services.challenge import add_flag, get_challenge

    try:
        challenge = get_challenge(challenge_id)
    except CTFNotFoundError:
        return JsonResponse({"error": "Challenge not found"}, status=404)

    forbidden = _check_event_ownership(challenge.event, _get_user(request))
    if forbidden:
        return forbidden

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    flag_type = body.get("flag_type", "static")
    flag_value = body.get("flag", "").strip()

    # Flag value is only required for static and regex types
    if flag_type in ("static", "regex") and not flag_value:
        return JsonResponse({"error": "Flag value is required"}, status=400)

    flag_data = {
        "flag": flag_value,
        "flag_type": flag_type,
        "case_sensitive": body.get("case_sensitive", True),
        "order": body.get("order", 0),
        "validator_config": body.get("validator_config"),
    }

    try:
        flag_obj = add_flag(challenge_id, flag_data)
        response_data = {
            "id": str(flag_obj.id),
            "flag_type": flag_obj.flag_type,
            "case_sensitive": flag_obj.case_sensitive,
            "order": flag_obj.order,
        }
        if flag_obj.validator_config:
            response_data["validator_config"] = flag_obj.validator_config
        return JsonResponse(response_data, status=201)
    except CTFNotFoundError as e:
        return JsonResponse({"error": str(e)}, status=404)
    except CTFStateError as e:
        return JsonResponse({"error": str(e)}, status=400)
    except CTFValidationError as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
@ctf_organizer_required
@require_POST
def api_remove_flag(request: HttpRequest, flag_id: UUID) -> JsonResponse:
    """API: Remove a flag from a challenge.

    Args:
        flag_id: UUID of the flag.
    """
    from ctf.exceptions import CTFNotFoundError, CTFStateError
    from ctf.models import CTFFlag
    from ctf.services.challenge import remove_flag

    try:
        flag_obj = CTFFlag.objects.select_related("challenge__event").get(pk=flag_id)
    except CTFFlag.DoesNotExist:
        return JsonResponse({"error": "Flag not found"}, status=404)

    forbidden = _check_event_ownership(flag_obj.challenge.event, _get_user(request))
    if forbidden:
        return forbidden

    try:
        remove_flag(flag_id)
        return JsonResponse({"success": True})
    except CTFNotFoundError as e:
        return JsonResponse({"error": str(e)}, status=404)
    except CTFStateError as e:
        return JsonResponse({"error": str(e)}, status=400)


# -----------------------------------------------------------------------------
# File Attachment API Views
# -----------------------------------------------------------------------------


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def api_challenge_files(request: HttpRequest, challenge_id: UUID) -> JsonResponse:
    """API: List and upload challenge files.

    GET: List files for a challenge.
    POST: Upload a file to a challenge.
    """
    from ctf.exceptions import CTFNotFoundError, CTFStateError, CTFValidationError
    from ctf.services.attachment import add_challenge_file, get_challenge_files
    from ctf.services.challenge import get_challenge

    try:
        challenge = get_challenge(challenge_id)
    except CTFNotFoundError:
        return JsonResponse({"error": "Challenge not found"}, status=404)

    forbidden = _check_event_ownership(challenge.event, _get_user(request))
    if forbidden:
        return forbidden

    if request.method == "GET":
        files = get_challenge_files(challenge_id)
        return JsonResponse(
            {
                "files": [
                    {
                        "id": str(f.id),
                        "filename": f.filename,
                        "display_name": f.display_name,
                        "file_size_bytes": f.file_size_bytes,
                        "file_size_display": f.file_size_display,
                        "content_type": f.content_type,
                        "sha256_hash": f.sha256_hash,
                        "order": f.order,
                        "created_at": f.created_at.isoformat(),
                    }
                    for f in files
                ]
            }
        )

    # POST: Upload file
    if not request.FILES.get("file"):
        return JsonResponse({"error": "No file provided"}, status=400)

    from django.core.files.uploadedfile import UploadedFile

    uploaded_file = cast(UploadedFile, request.FILES["file"])
    display_name = request.POST.get("display_name", "")

    try:
        challenge_file = add_challenge_file(
            challenge_id=challenge_id,
            file_obj=uploaded_file,
            filename=uploaded_file.name or "unnamed",
            display_name=display_name,
            content_type=uploaded_file.content_type or "application/octet-stream",
        )
        return JsonResponse(
            {
                "id": str(challenge_file.id),
                "filename": challenge_file.filename,
                "display_name": challenge_file.display_name,
                "file_size_bytes": challenge_file.file_size_bytes,
                "file_size_display": challenge_file.file_size_display,
            },
            status=201,
        )
    except CTFNotFoundError as e:
        return JsonResponse({"error": str(e)}, status=404)
    except CTFStateError as e:
        return JsonResponse({"error": str(e)}, status=400)
    except CTFValidationError as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
@ctf_organizer_required
@require_POST
def api_challenge_file_delete(request: HttpRequest, file_id: UUID) -> JsonResponse:
    """API: Delete a challenge file.

    Args:
        file_id: UUID of the file to delete.
    """
    from ctf.exceptions import CTFNotFoundError, CTFStateError
    from ctf.models import CTFChallengeFile
    from ctf.services.attachment import remove_challenge_file

    try:
        challenge_file = CTFChallengeFile.objects.select_related("challenge__event").get(pk=file_id)
    except CTFChallengeFile.DoesNotExist:
        return JsonResponse({"error": "File not found"}, status=404)

    forbidden = _check_event_ownership(challenge_file.challenge.event, _get_user(request))
    if forbidden:
        return forbidden

    try:
        remove_challenge_file(file_id)
        return JsonResponse({"success": True})
    except CTFNotFoundError as e:
        return JsonResponse({"error": str(e)}, status=404)
    except CTFStateError as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
@require_GET
def api_file_download(request: HttpRequest, file_id: UUID) -> HttpResponse:
    """API: Get a presigned download URL for a challenge file.

    Accessible by organizers and participants (for challenges in their event).
    """
    from ctf.exceptions import CTFNotFoundError
    from ctf.models import CTFChallengeFile
    from ctf.services.attachment import get_download_url

    # Verify access: check the file exists and user has access
    try:
        challenge_file = CTFChallengeFile.objects.select_related("challenge__event").get(pk=file_id)
    except CTFChallengeFile.DoesNotExist:
        return JsonResponse({"error": "File not found"}, status=404)

    user = _get_user(request)
    event = challenge_file.challenge.event

    # Check: organizer or participant in this event
    from ctf.bridges import get_user_role
    from ctf.models import CTFParticipant

    role = get_user_role(user)
    has_access = False
    if role.is_ctf_organizer and event.created_by_id == user.pk:
        has_access = True
    else:
        has_access = CTFParticipant.objects.filter(
            event=event,
            user=user,
            registered_at__isnull=False,
        ).exists()

    if not has_access:
        return HttpResponse("Forbidden", status=403)

    try:
        url, _filename = get_download_url(file_id)
    except CTFNotFoundError as e:
        return JsonResponse({"error": str(e)}, status=404)

    # Return the presigned URL for client-side navigation instead of a
    # server-side redirect.  This avoids open-redirect risk (S5146) since the
    # server never issues an HTTP 302 to a dynamically constructed URL.
    return JsonResponse({"url": url, "filename": _filename})


@login_required
@ctf_organizer_required
@require_POST
def admin_challenge_file_upload(request: HttpRequest, challenge_id: UUID) -> HttpResponse:
    """Upload a challenge file from the admin detail page.

    Redirects back to the challenge detail page.
    """
    from ctf.exceptions import CTFNotFoundError, CTFStateError, CTFValidationError
    from ctf.services.attachment import add_challenge_file
    from ctf.services.challenge import get_challenge

    try:
        challenge = get_challenge(challenge_id)
    except CTFNotFoundError:
        return redirect("ctf:admin_challenge_detail", challenge_id=challenge_id)

    if challenge.event.created_by_id != request.user.pk:
        return HttpResponse("Forbidden", status=403)

    if not request.FILES.get("file"):
        return redirect("ctf:admin_challenge_detail", challenge_id=challenge_id)

    from django.core.files.uploadedfile import UploadedFile

    uploaded_file = cast(UploadedFile, request.FILES["file"])
    display_name = request.POST.get("display_name", "")

    try:
        add_challenge_file(
            challenge_id=challenge_id,
            file_obj=uploaded_file,
            filename=uploaded_file.name or "unnamed",
            display_name=display_name,
            content_type=uploaded_file.content_type or "application/octet-stream",
        )
    except (CTFNotFoundError, CTFStateError, CTFValidationError) as e:
        logger.warning("File upload failed for challenge %s: %s", challenge_id, e)

    return redirect("ctf:admin_challenge_detail", challenge_id=challenge_id)


# -----------------------------------------------------------------------------
# Prerequisite API Views
# -----------------------------------------------------------------------------


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def api_challenge_prerequisites(request: HttpRequest, challenge_id: UUID) -> JsonResponse:
    """API: List and add challenge prerequisites.

    GET: List prerequisites for a challenge.
    POST: Add a prerequisite to a challenge.
    """
    from ctf.exceptions import CTFNotFoundError, CTFStateError, CTFValidationError
    from ctf.services.challenge import add_prerequisite, get_challenge, get_prerequisites

    try:
        challenge = get_challenge(challenge_id)
    except CTFNotFoundError:
        return JsonResponse({"error": "Challenge not found"}, status=404)

    forbidden = _check_event_ownership(challenge.event, _get_user(request))
    if forbidden:
        return forbidden

    if request.method == "GET":
        prereqs = get_prerequisites(challenge_id)
        return JsonResponse(
            {
                "prerequisites": [
                    {
                        "id": str(p.id),
                        "required_challenge_id": str(p.required_challenge_id),
                        "required_challenge_name": p.required_challenge.name,
                        "required_challenge_category": p.required_challenge.category,
                        "required_challenge_points": p.required_challenge.points,
                    }
                    for p in prereqs
                ]
            }
        )

    # POST: Add prerequisite
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    required_challenge_id = body.get("required_challenge_id")
    if not required_challenge_id:
        return JsonResponse({"error": "required_challenge_id is required"}, status=400)

    try:
        prereq = add_prerequisite(challenge_id, UUID(required_challenge_id))
        return JsonResponse(
            {
                "id": str(prereq.id),
                "required_challenge_id": str(prereq.required_challenge_id),
                "required_challenge_name": prereq.required_challenge.name,
            },
            status=201,
        )
    except CTFNotFoundError as e:
        return JsonResponse({"error": str(e)}, status=404)
    except CTFStateError as e:
        return JsonResponse({"error": str(e)}, status=400)
    except CTFValidationError as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
@ctf_organizer_required
@require_POST
def api_prerequisite_delete(request: HttpRequest, prerequisite_id: UUID) -> JsonResponse:
    """API: Remove a prerequisite.

    Args:
        prerequisite_id: UUID of the prerequisite to remove.
    """
    from ctf.exceptions import CTFNotFoundError, CTFStateError
    from ctf.models import CTFChallengePrerequisite
    from ctf.services.challenge import remove_prerequisite

    try:
        prereq = CTFChallengePrerequisite.objects.select_related("challenge__event").get(pk=prerequisite_id)
    except CTFChallengePrerequisite.DoesNotExist:
        return JsonResponse({"error": "Prerequisite not found"}, status=404)

    forbidden = _check_event_ownership(prereq.challenge.event, _get_user(request))
    if forbidden:
        return forbidden

    try:
        remove_prerequisite(prerequisite_id)
        return JsonResponse({"success": True})
    except CTFNotFoundError as e:
        return JsonResponse({"error": str(e)}, status=404)
    except CTFStateError as e:
        return JsonResponse({"error": str(e)}, status=400)
