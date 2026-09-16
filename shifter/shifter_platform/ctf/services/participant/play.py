"""Shared participant challenge-play presentation helpers.

These pure computations (next-hint cost, attempt-limit state, target connection
info) sit between the authoritative services (scoring, submission attempt
counting, range target resolution) and the canonical ``ctf.api`` participant
detail projection consumed by the SPA.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.utils import timezone

if TYPE_CHECKING:
    from collections.abc import Iterable
    from uuid import UUID

    from django.db.models import QuerySet

    from ctf.models import CTFChallenge, CTFEvent, CTFHint, CTFParticipant, CTFSubmission


def compute_hint_purchase_info(
    event: CTFEvent,
    challenge: CTFChallenge,
    all_hints: Iterable[CTFHint],
    unlocked_hint_ids: set[UUID],
    total_hint_penalty: int,
) -> dict[str, Any]:
    """Compute next-hint, cost, and warning state for the challenge detail view.

    Projected values dispatch through the event's scoring mode so the displayed
    cost matches how a solve is scored.
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


def match_target_instance(challenge: CTFChallenge, instances: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
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


def resolve_target_connection_info(challenge: CTFChallenge, participant: CTFParticipant) -> dict[str, Any] | None:
    """Return connection-info dict for the challenge's target instance, or None."""
    participant_user = participant.user
    if not challenge.target_instance_name or participant.range_status != "ready" or participant_user is None:
        return None
    import cms.services as cms_services

    return match_target_instance(challenge, cms_services.get_range_target_instances(participant_user))


def compute_attempt_state(
    challenge: CTFChallenge,
    participant: CTFParticipant,
    submissions: QuerySet[CTFSubmission],
    attempt_count: int,
) -> tuple[int, int | None, int | None]:
    """Return ``(attempt_count, timeout_retry_after, attempts_remaining)``.

    Recomputes ``attempt_count`` under "timeout" attempt-limit mode (counts only
    the current cooldown window) and derives the retry-after timer and
    remaining-attempts display.
    """
    timeout_retry_after = None
    if participant.event.attempt_limit_mode == "timeout" and challenge.max_attempts > 0:
        from ctf.services.submission_gates import _count_attempts_in_current_window

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
