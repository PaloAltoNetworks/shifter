"""Participant challenge list and challenge-detail HTML views."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import urlencode
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse

if TYPE_CHECKING:
    from django.http import HttpRequest


from ctf.services.participant.play import (
    compute_attempt_state as _compute_attempt_state,
)
from ctf.services.participant.play import (
    compute_hint_purchase_info as _compute_hint_purchase_info,
)
from ctf.services.participant.play import (
    resolve_target_connection_info as _resolve_target_connection_info,
)
from ctf.views import _access
from ctf.views._access import (
    ctf_participant_required,
)

logger = logging.getLogger(__name__)

_MISSION_CATEGORY = re.compile(r"^Mission\s+(\d+)\b", re.IGNORECASE)


class _NamedItem(Protocol):
    """Minimal shape the filter-link builder needs from a tag/topic: a ``name``."""

    name: str


def _category_sort_key(category: str) -> tuple[int, int, str]:
    """Put onboarding first, then authored missions in numeric order."""
    normalized = category.strip()
    if normalized.casefold() == "start here":
        return (0, 0, normalized.casefold())
    mission = _MISSION_CATEGORY.match(normalized)
    if mission:
        return (1, int(mission.group(1)), normalized.casefold())
    return (2, 0, normalized.casefold())


def _filter_query(*pairs: tuple[str, str | None]) -> str:
    """Build a relative ``?k=v&...`` query string, dropping empty values (empty if none)."""
    present = [(key, value) for key, value in pairs if value]
    return "?" + urlencode(present) if present else ""


def _build_challenge_filter_links(
    event_tags: Iterable[_NamedItem],
    event_topics: Iterable[_NamedItem],
    *,
    category_filter: str | None,
    tag_filter: str | None,
    topic_filter: str | None,
) -> dict[str, Any]:
    """Relative filter-link URLs for the challenge-list tag/topic buttons.

    Returns the two "All" URLs plus per-tag/per-topic ``{name, url, active}`` lists
    so the template renders one short ``<a href>`` per button (no inline query
    building, no duplicate mutually-exclusive link branches).
    """
    return {
        "tags_all_url": _filter_query(("category", category_filter)),
        "tag_filters": [
            {
                "name": tag.name,
                "url": _filter_query(("tag", tag.name), ("category", category_filter)),
                "active": tag_filter == tag.name,
            }
            for tag in event_tags
        ],
        "topics_all_url": _filter_query(("category", category_filter), ("tag", tag_filter)),
        "topic_filters": [
            {
                "name": topic.name,
                "url": _filter_query(("topic", topic.name), ("category", category_filter), ("tag", tag_filter)),
                "active": topic_filter == topic.name,
            }
            for topic in event_topics
        ],
    }


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

    # Categories are organizer-authored tracks (for example, external scenario mission
    # names), not a platform-owned taxonomy. Keep friendly labels for the
    # built-in technical defaults while preserving authored labels verbatim.
    from ctf.enums import ChallengeCategory

    default_category_labels = dict(ChallengeCategory.choices())
    category_values = sorted(
        challenges.order_by("category").values_list("category", flat=True).distinct(),
        key=_category_sort_key,
    )
    categories = [(value, default_category_labels.get(value, value)) for value in category_values]

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

    challenge_list.sort(
        key=lambda challenge: (
            _category_sort_key(challenge.category),
            challenge.order,
            challenge.name.casefold(),
        )
    )

    # Group by category
    challenges_by_category = defaultdict(list)
    for challenge in challenge_list:
        challenges_by_category[challenge.category].append(challenge)

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
        "categories": categories,
        "event_tags": event_tags,
        "event_topics": event_topics,
        "solved_ids": solved_ids,
        "locked_ids": locked_ids,
        # Precomputed filter-link URLs so the template renders one short <a href>
        # per tag/topic button (see _build_challenge_filter_links).
        **_build_challenge_filter_links(
            event_tags,
            event_topics,
            category_filter=category_filter,
            tag_filter=tag_filter,
            topic_filter=topic_filter,
        ),
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
        # Client bootstrap payload rendered via ``json_script`` so the template
        # stays within SonarCloud's inline-JS length limit; ctf-challenge-detail.js
        # reads it from the ``#ctf-challenge-detail-config`` element.
        "challenge_detail_config": {
            "submitFlagUrl": reverse("v1:ctf:api_submit_flag", kwargs={"challenge_id": challenge.pk}),
            "useHintUrl": reverse("v1:ctf:api_use_hint", kwargs={"challenge_id": challenge.pk}),
            "rateChallengeUrl": reverse("v1:ctf:api_rate_challenge", kwargs={"challenge_id": challenge.pk}),
            "challengePoints": challenge.points or 0,
            "totalHintPenalty": total_hint_penalty or 0,
        },
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
