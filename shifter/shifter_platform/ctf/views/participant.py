"""Participant-facing HTML views (registration, dashboard, range, scoreboard, team)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods

if TYPE_CHECKING:
    from uuid import UUID

    from django.http import HttpRequest

    from ctf.models import CTFParticipant

from ctf.views import _access, _parsing
from ctf.views._access import (
    ctf_participant_required,
    ctf_role_required,
)

logger = logging.getLogger(__name__)

_SCOREBOARD_TEMPLATE = "ctf/participant/scoreboard.html"
_SOLVE_HISTORY_TEMPLATE = "ctf/participant/solve_history.html"


@login_required
@ctf_participant_required
def participant_dashboard(request: HttpRequest) -> HttpResponse:
    """Participant main dashboard.

    Shows event overview, challenge progress, and quick links.
    """
    from ctf.services.challenge import get_available_challenges
    from ctf.services.scoring import calculate_score, get_participant_rank

    participant = _access._get_active_participant(request)
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

    participant = _access._get_active_participant(request)
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
def participant_range(request: HttpRequest) -> HttpResponse:
    """Participant range status and access.

    Shows range provisioning status and access URLs.
    """

    participant = _access._get_active_participant(request)
    if not participant:
        return render(request, "ctf/participant/range.html", {})

    # Look up provisioned instances (with IPs) via CMS services
    target_instances = []
    if participant.range_instance_id and participant.range_status == "ready" and participant.user:
        import cms.services as cms_services

        target_instances = cms_services.get_range_target_instances(participant.user)

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

    Shows rankings for current event. Supports bracket filtering
    via ?bracket=<uuid> query parameter.
    """
    from ctf.services.scoring import get_scoreboard, get_team_scoreboard

    participant = _access._get_active_participant(request)
    if not participant:
        return render(request, _SCOREBOARD_TEMPLATE, {})

    event = participant.event

    # URLs the scoreboard auto-refresh JS reads from #scoreboard-config. Built
    # server-side so the template's data-* attributes stay under Sonar's line
    # length limit (Web:MaxLineLengthCheck).
    solve_history_url = reverse("ctf:participant_solve_history", kwargs={"participant_id": participant.pk})

    # If organizer has hidden the scoreboard, show a hidden message
    if not event.scoreboard_visible:
        return render(
            request,
            _SCOREBOARD_TEMPLATE,
            {
                "participant": participant,
                "event": event,
                "scoreboard_hidden": True,
                "scoreboard_url": reverse("ctf:api_scoreboard", kwargs={"event_id": event.id}),
                "solve_history_url": solve_history_url,
            },
        )

    freeze_at = event.scoreboard_freeze_at if event.is_scoreboard_frozen else None
    brackets, selected_bracket, bracket_id = _parsing._resolve_bracket_filter(event.id, request.GET.get("bracket"))

    scoreboard_url = reverse("ctf:api_scoreboard", kwargs={"event_id": event.id})
    if selected_bracket:
        scoreboard_url = f"{scoreboard_url}?bracket={selected_bracket.id}"

    rankings = (
        get_team_scoreboard(event.id, freeze_at=freeze_at)
        if event.team_mode
        else get_scoreboard(event.id, freeze_at=freeze_at)
    )

    bracket_rankings = None
    if bracket_id:
        bracket_rankings = (
            get_team_scoreboard(event.id, freeze_at=freeze_at, bracket_id=bracket_id)
            if event.team_mode
            else get_scoreboard(event.id, freeze_at=freeze_at, bracket_id=bracket_id)
        )

    context = {
        "participant": participant,
        # The scoreboard row partial and the auto-refresh JS both key the
        # "You" highlight on ``participant_id``; without it in the context the
        # highlight is dead on initial render and on refresh (issue #521).
        "participant_id": str(participant.id),
        "event": event,
        "rankings": rankings,
        "bracket_rankings": bracket_rankings,
        "brackets": brackets,
        "selected_bracket": selected_bracket,
        "team_mode": event.team_mode,
        "frozen": event.is_scoreboard_frozen,
        "scoreboard_url": scoreboard_url,
        "solve_history_url": solve_history_url,
    }
    return render(request, _SCOREBOARD_TEMPLATE, context)


def _resolve_solve_history_access(
    request: HttpRequest, participant_id: UUID
) -> tuple[CTFParticipant | None, bool, HttpResponse | None]:
    """Resolve the target participant and authorize solve-history access.

    Returns ``(target, is_event_organizer, error_response)``. Access is
    own-participant-or-event-organizer (issue #521 / CTF-401): a participant may
    open only their own history; the organizer that owns the event may open any
    participant's. Keeping the 404/403 returns here holds the view itself to a
    single render path per outcome.
    """
    from ctf.exceptions import CTFNotFoundError
    from ctf.services import get_participant

    try:
        target = get_participant(participant_id)
    except CTFNotFoundError:
        return None, False, HttpResponse("Not found", status=404)

    user = _access._get_user(request)
    role = _access.get_user_role(user)
    is_event_organizer = role.is_ctf_organizer and target.event.created_by_id == user.pk
    if target.user_id != user.pk and not is_event_organizer:
        logger.warning(
            "CTF solve-history access denied for user %s on participant %s",
            user.email,
            target.id,
        )
        return None, False, HttpResponse("Forbidden", status=403)

    return target, is_event_organizer, None


@login_required
@ctf_role_required
@require_GET
def participant_solve_history(request: HttpRequest, participant_id: UUID) -> HttpResponse:
    """Own-row solve-history drill-down from a scoreboard row.

    Scope (issue #521 / CTF-401): a participant may open only their own solve
    history; the event organizer may open any participant's history for events
    they own. The projection is correct-solves-only and secret-safe (see
    ``get_participant_solve_history``); ranking/tie-break semantics stay in
    ``ctf.services.scoring`` and are not recomputed here.

    Args:
        participant_id: UUID of the participant whose history to render.
    """
    from ctf.services.submission import get_participant_solve_history

    target, is_event_organizer, error = _resolve_solve_history_access(request, participant_id)
    if error is not None:
        return error
    assert target is not None

    event = target.event
    # Non-organizers must not see history while the organizer has the
    # scoreboard hidden, mirroring the scoreboard visibility gate.
    if not is_event_organizer and not event.scoreboard_visible:
        return render(
            request,
            _SOLVE_HISTORY_TEMPLATE,
            {"participant": target, "event": event, "scoreboard_hidden": True},
        )

    # Apply the same frozen-scoreboard cutoff as the scoreboard itself: a
    # non-organizer viewer must not see solves submitted after the freeze,
    # since those rows are intentionally absent from the frozen scoreboard.
    # Organizers always see the live history.
    freeze_at = event.scoreboard_freeze_at if (event.is_scoreboard_frozen and not is_event_organizer) else None

    context = {
        "participant": target,
        "event": event,
        "frozen": event.is_scoreboard_frozen and not is_event_organizer,
        "solves": get_participant_solve_history(target.id, freeze_at=freeze_at),
    }
    return render(request, _SOLVE_HISTORY_TEMPLATE, context)


@login_required
@ctf_participant_required
def participant_team(request: HttpRequest) -> HttpResponse:
    """Participant team view.

    Shows team members and team-specific information.
    """

    participant = _access._get_active_participant(request)
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

    participant = _access._get_active_participant(request)
    if not participant:
        return render(request, "ctf/participant/team_join.html", {})

    event = participant.event
    error = None

    if request.method == "POST":
        from ctf.exceptions import CTFError
        from ctf.services.team import join_team

        invite_code = request.POST.get("invite_code", "").strip()
        try:
            join_team(participant.pk, invite_code)
        except CTFError as exc:
            error = exc.message
        else:
            return redirect("ctf:participant_team")

    context = {
        "participant": participant,
        "event": event,
        "error": error,
    }
    return render(request, "ctf/participant/team_join.html", context)


@require_GET
def ctf_help(request: HttpRequest) -> HttpResponse:
    """CTF help page.

    Public help page for CTF participants.
    """
    return render(request, "ctf/help.html")
