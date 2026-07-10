"""Participant challenge list and challenge-detail HTML views."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.db.models import QuerySet
    from django.http import HttpRequest

    from ctf.models import (
        CTFChallenge,
        CTFEvent,
        CTFHint,
        CTFParticipant,
        CTFSubmission,
    )

from ctf.views import _access
from ctf.views._access import (
    ctf_participant_required,
)

logger = logging.getLogger(__name__)


@login_required
@ctf_participant_required
def participant_challenges(request: HttpRequest) -> HttpResponse:
    """Participant challenges list.

    Shows available challenges with solve status.
    """
    from collections import defaultdict

    from ctf.services.challenge import get_available_challenges
    from ctf.services.submission import get_participant_submissions

    participant = _access._get_active_participant(request)
    if not participant:
        return render(request, "ctf/participant/challenges.html", {})

    event = participant.event
    challenges = get_available_challenges(event.id).prefetch_related("tags", "topics")

    # Apply category filter if provided
    category_filter = request.GET.get("category")
    if category_filter:
        challenges = challenges.filter(category=category_filter)

    # Apply tag filter if provided
    tag_filter = request.GET.get("tag")
    if tag_filter:
        challenges = challenges.filter(tags__name=tag_filter).distinct()

    # Apply topic filter if provided
    topic_filter = request.GET.get("topic")
    if topic_filter:
        challenges = challenges.filter(topics__name=topic_filter).distinct()

    # Build set of solved challenge IDs
    correct_submissions = get_participant_submissions(participant.id).filter(is_correct=True)
    solved_ids = set(correct_submissions.values_list("challenge_id", flat=True))

    # Build prerequisite info: which challenges have unmet prerequisites
    from ctf.models import CTFChallengePrerequisite

    all_prereqs = CTFChallengePrerequisite.objects.filter(
        challenge__event_id=event.id,
    ).select_related("required_challenge")

    # Map challenge_id -> list of required challenge names
    prereqs_by_challenge: dict[UUID, list[Any]] = defaultdict(list)
    locked_ids: set[UUID] = set()
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

    # Get all topics used by challenges in this event
    from ctf.models import CTFTopic

    event_topics = (
        CTFTopic.objects.filter(
            challenges__event=event,
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
        "topic_filter": topic_filter,
        "categories": ChallengeCategory,
        "event_tags": event_tags,
        "event_topics": event_topics,
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
    from ctf.services.submission import get_participant_submissions

    try:
        challenge = get_challenge(challenge_id)
    except CTFNotFoundError:
        raise Http404("Challenge not found") from None

    # Resolve the participant for THIS challenge's event (issue #765/#768/#769
    # codex cycle 4): a multi-event user must be looked up scoped to the
    # route's event, not via an arbitrary first-row pick that could land on
    # the wrong event entirely.
    participant = _access._get_participant_for_challenge(request, challenge)
    if not participant:
        return HttpResponse("Forbidden", status=403)

    # Codex cycle 8: use the read-availability policy (not the submit/hint
    # write-policy). This blocks HIDDEN, unreleased, and prerequisite-gated
    # content while still allowing LOCKED challenges (documented as
    # shown-but-not-submittable) and ENDED/ARCHIVED events (where
    # `show_solution` is intentionally surfaced for review).
    from ctf.exceptions import CTFStateError, CTFValidationError
    from ctf.services.challenge import assert_challenge_readable_for_participant

    try:
        assert_challenge_readable_for_participant(participant, challenge)
    except (CTFStateError, CTFValidationError):
        return HttpResponse("Forbidden", status=403)

    # Get participant's submissions for this challenge
    submissions = get_participant_submissions(participant.id, challenge_id=challenge_id)
    is_solved = submissions.filter(is_correct=True).exists()
    attempt_count = submissions.count()

    # Get progressive hints and unlock status
    from ctf.services.hint import get_hints, get_total_hint_penalty, get_unlocked_hints

    all_hints = list(get_hints(challenge_id))
    unlocked_hint_ids = {h.id for h in get_unlocked_hints(participant.id, challenge_id)}
    total_hint_penalty = get_total_hint_penalty(participant.id, challenge_id)
    hint_purchase = _compute_hint_purchase_info(
        participant.event,
        challenge,
        all_hints,
        unlocked_hint_ids,
        total_hint_penalty,
    )

    from ctf.services.attachment import get_challenge_files
    from ctf.services.challenge import check_prerequisites_met

    challenge_files = get_challenge_files(challenge_id)
    prereqs_met, unmet_challenges = check_prerequisites_met(challenge_id, participant.id)
    connection_info = _resolve_target_connection_info(challenge, participant)
    attempt_count, timeout_retry_after, attempts_remaining = _compute_attempt_state(
        challenge, participant, submissions, attempt_count
    )

    context = {
        "participant": participant,
        "challenge": challenge,
        "event": participant.event,
        "submissions": submissions,
        "is_solved": is_solved,
        "attempt_count": attempt_count,
        "hints": all_hints,
        "unlocked_hint_ids": unlocked_hint_ids,
        "next_hint": hint_purchase["next_hint"],
        "next_hint_cost": hint_purchase["next_hint_cost"],
        "points_after_next_hint": hint_purchase["points_after_next_hint"],
        "penalty_warning": hint_purchase["penalty_warning"],
        "total_hint_penalty": total_hint_penalty,
        "max_attempts": challenge.max_attempts,
        "attempts_remaining": attempts_remaining,
        "challenge_files": challenge_files,
        "prereqs_met": prereqs_met,
        "unmet_challenges": unmet_challenges,
        "connection_info": connection_info,
        "attempt_limit_mode": participant.event.attempt_limit_mode,
        "timeout_retry_after": timeout_retry_after,
        "show_solution": bool(challenge.solution and participant.event.status in ("ended", "archived")),
    }

    # Add rating context
    rating_visibility = participant.event.rating_visibility
    if rating_visibility != "disabled":
        from ctf.services.submission import get_challenge_rating

        rating_data = get_challenge_rating(challenge_id)
        context["rating"] = rating_data
        context["show_ratings"] = rating_visibility == "public"
        # Get participant's own rating if they have one
        from ctf.models import CTFChallengeRating

        own_rating_obj = CTFChallengeRating.objects.filter(participant=participant, challenge=challenge).first()
        own_rating_value = own_rating_obj.value if own_rating_obj else None
        context["own_rating"] = own_rating_value
        # Pre-compute button states for template (avoids broken template filter math)
        context["rating_buttons"] = [{"value": i, "active": own_rating_value == i} for i in range(1, 6)]

    return render(request, "ctf/participant/challenge_detail.html", context)


def _compute_hint_purchase_info(
    event: CTFEvent,
    challenge: CTFChallenge,
    all_hints: Iterable[CTFHint],
    unlocked_hint_ids: set[UUID],
    total_hint_penalty: int,
) -> dict[str, Any]:
    """Compute next-hint, cost, and warning state for the challenge detail page.

    Extracted to keep `challenge_detail`'s cognitive complexity below the
    SonarCloud threshold (python:S3776). Projected values dispatch through the
    event's scoring mode so the displayed cost matches how a solve is scored.
    """
    from ctf.services.scoring import calculate_solve_points

    next_hint = next((h for h in all_hints if h.id not in unlocked_hint_ids), None)
    next_hint_cost = 0
    points_after_next_hint = challenge.points
    penalty_warning = False
    if next_hint and next_hint.penalty > 0:
        current_value = calculate_solve_points(event, challenge, total_hint_penalty)
        projected_penalty = total_hint_penalty + next_hint.penalty
        points_after_next_hint = calculate_solve_points(event, challenge, projected_penalty)
        next_hint_cost = current_value - points_after_next_hint
        penalty_warning = projected_penalty >= 100
    return {
        "next_hint": next_hint,
        "next_hint_cost": next_hint_cost,
        "points_after_next_hint": points_after_next_hint,
        "penalty_warning": penalty_warning,
    }


def _match_target_instance(challenge: CTFChallenge, instances: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    """Return connection info for the instance matching the challenge target, or None."""
    for inst in instances:
        if inst.get("name") != challenge.target_instance_name:
            continue
        host = inst.get("private_ip")
        if not host:
            return None
        return {
            "host": host,
            "port": challenge.target_port,
            "instance_name": inst["name"],
            "os_type": inst.get("os_type", ""),
        }
    return None


def _resolve_target_connection_info(challenge: CTFChallenge, participant: CTFParticipant) -> dict[str, Any] | None:
    """Return connection-info dict for the challenge's target instance, or None.

    Extracted from `challenge_detail` (SonarCloud python:S3776).
    """
    participant_user = participant.user
    if not challenge.target_instance_name or participant.range_status != "ready" or participant_user is None:
        return None
    import cms.services as cms_services

    return _match_target_instance(challenge, cms_services.get_range_target_instances(participant_user.pk))


def _compute_attempt_state(
    challenge: CTFChallenge,
    participant: CTFParticipant,
    submissions: QuerySet[CTFSubmission],
    attempt_count: int,
) -> tuple[int, int | None, int | None]:
    """Return `(attempt_count, timeout_retry_after, attempts_remaining)`.

    Extracted from `challenge_detail` (SonarCloud python:S3776). Recomputes
    `attempt_count` under "timeout" attempt-limit mode (counts only the
    current cooldown window) and derives the retry-after timer and
    remaining-attempts display.
    """
    timeout_retry_after = None
    if participant.event.attempt_limit_mode == "timeout" and challenge.max_attempts > 0:
        from ctf.services.submission import _count_attempts_in_current_window

        attempt_cooldown = participant.event.attempt_limit_cooldown_seconds
        attempt_count = _count_attempts_in_current_window(submissions, attempt_cooldown)
        if attempt_count >= challenge.max_attempts:
            last_sub = submissions.first()
            if last_sub:
                elapsed = (timezone.now() - last_sub.submitted_at).total_seconds()
                if elapsed < attempt_cooldown:
                    timeout_retry_after = int(attempt_cooldown - elapsed) + 1
    attempts_remaining = max(0, challenge.max_attempts - attempt_count) if challenge.max_attempts else None
    return attempt_count, timeout_retry_after, attempts_remaining
