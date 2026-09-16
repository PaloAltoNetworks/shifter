"""Server-owned participant-safe projections for the canonical CTF API.

These functions are the single place the participant ``/api/v1/ctf/me/*`` reads
are shaped. They compose the already-audited ``ctf.services.*`` facades and
return plain dicts that the DRF serializers in :mod:`ctf.api.serializers` type.

Permission-sensitive fields (flag hashes, flag formats, validator config,
solutions, unreleased/hidden content, other participants' scores) are filtered
here, server-side, so the participant surface can never leak them regardless of
what the client requests. Domain correctness (availability policy, prerequisite
gating, scoring) stays in the service layer; these helpers only marshal a
participant-safe view of it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ctf.services.challenge import get_available_challenges
from ctf.services.submission import get_participant_submissions

if TYPE_CHECKING:
    from ctf.models import CTFChallenge, CTFEvent, CTFParticipant


def participant_current_event(participant: CTFParticipant) -> dict[str, Any]:
    """Return the participant's current event plus their own participant state.

    The event fields are the read-only shape the participant workspace needs to
    render (scoring mode, team mode, scoreboard/attempt policy, window). No
    organizer-only configuration (range_config, reminder schedule, spare counts,
    email templates) is included.
    """
    event = participant.event
    return {
        "event": {
            "id": str(event.id),
            "name": event.name,
            "description": event.description,
            "status": event.status,
            "team_mode": event.team_mode,
            "scoring_mode": event.scoring_mode,
            "rating_visibility": event.rating_visibility,
            "attempt_limit_mode": event.attempt_limit_mode,
            "scoreboard_visible": event.scoreboard_visible,
            "scoreboard_visibility": event.scoreboard_visibility,
            "event_start": event.event_start,
            "event_end": event.event_end,
            "registration_deadline": event.effective_registration_deadline,
            "rules": event.rules,
            "logo_url": event.logo_url,
            "theme_color": event.theme_color,
        },
        "participant": _participant_self(participant),
    }


def _participant_self(participant: CTFParticipant) -> dict[str, Any]:
    """Return the participant's own state (never another participant's)."""
    team = participant.team
    bracket = participant.bracket
    return {
        "id": str(participant.id),
        "name": participant.name,
        "status": participant.status,
        "role": participant.role,
        "affiliation": participant.affiliation,
        "range_status": participant.range_status,
        "cached_score": participant.cached_score,
        "cached_solve_count": participant.cached_solve_count,
        "team": {"id": str(team.id), "name": team.name} if team is not None else None,
        "bracket": {"id": str(bracket.id), "name": bracket.name} if bracket is not None else None,
    }


def participant_challenge_list(participant: CTFParticipant) -> list[dict[str, Any]]:
    """Return the participant-safe browse list of available challenges.

    Uses the availability policy in :func:`ctf.services.challenge.get_available_challenges`
    (hidden/unreleased excluded, prerequisite-gated challenges excluded for this
    participant) and overlays this participant's own solve state. Flag hashes,
    flag formats, solutions, and validator config are never included.
    """
    challenges = get_available_challenges(participant.event_id, participant_id=participant.id).prefetch_related(
        "tags", "topics"
    )
    solved_ids = set(
        get_participant_submissions(participant.id).filter(is_correct=True).values_list("challenge_id", flat=True)
    )
    return [
        {
            "id": str(challenge.id),
            "name": challenge.name,
            "category": challenge.category,
            "points": challenge.points,
            "difficulty": challenge.difficulty,
            "order": challenge.order,
            "solved": challenge.id in solved_ids,
            "tags": [tag.name for tag in challenge.tags.all()],
            "topics": [topic.name for topic in challenge.topics.all()],
        }
        for challenge in challenges
    ]


def participant_team(participant: CTFParticipant) -> dict[str, Any] | None:
    """Return the participant's team and its members, or ``None`` when unteamed.

    Only teammate display names are exposed (no per-member scores or accounts),
    and only for the participant's own team. Returns ``None`` for solo events or
    an unassigned participant so the caller can render an empty state.
    """
    team = participant.team
    if team is None:
        return None
    members = team.members.filter(deleted_at__isnull=True).order_by("name")
    is_captain = team.captain_id == participant.pk
    return {
        "id": str(team.id),
        "name": team.name,
        "members": [
            {
                "id": str(member.id),
                "name": member.name,
                "is_captain": member.id == team.captain_id,
            }
            for member in members
        ],
        "is_captain": is_captain,
        "team_size_limit": team.event.team_size_limit,
        # The invite code is the joining secret; only the captain sees it.
        "invite_code": team.invite_code if is_captain else None,
    }


def participant_challenge_detail(participant: CTFParticipant, challenge: CTFChallenge) -> dict[str, Any]:
    """Return the participant-safe detail projection for one challenge.

    Composes the canonical challenge / hint / submission / scoring services and
    the shared play helpers (:mod:`ctf.services.participant.play`). The flag
    hash, flag format, and validator configuration are never included; hint text
    is present only for hints this participant has unlocked; the solution is
    surfaced only once the event has ended/archived, matching the legacy
    participant-detail policy. The caller MUST have already asserted the
    challenge is readable for this participant.
    """
    from ctf.services.attachment import get_challenge_files
    from ctf.services.challenge import check_prerequisites_met
    from ctf.services.hint import get_hints, get_total_hint_penalty, get_unlocked_hints
    from ctf.services.participant.play import (
        compute_attempt_state,
        compute_hint_purchase_info,
        resolve_target_connection_info,
    )

    event = participant.event
    submissions = get_participant_submissions(participant.id, challenge_id=challenge.id)
    is_solved = submissions.filter(is_correct=True).exists()

    all_hints = list(get_hints(challenge.id))
    unlocked_ids = {hint.id for hint in get_unlocked_hints(participant.id, challenge.id)}
    total_hint_penalty = get_total_hint_penalty(participant.id, challenge.id)
    hint_purchase = compute_hint_purchase_info(event, challenge, all_hints, unlocked_ids, total_hint_penalty)
    next_hint = hint_purchase["next_hint"]

    prereqs_met, unmet = check_prerequisites_met(challenge.id, participant.id)
    attempt_count, timeout_retry_after, attempts_remaining = compute_attempt_state(
        challenge, participant, submissions, submissions.count()
    )
    show_solution = bool(challenge.solution and event.status in ("ended", "archived"))

    return {
        "id": str(challenge.id),
        "name": challenge.name,
        "description": challenge.description,
        "category": challenge.category,
        "tags": [tag.name for tag in challenge.tags.all()],
        "topics": [topic.name for topic in challenge.topics.all()],
        "points": challenge.points,
        "difficulty": challenge.difficulty,
        "max_attempts": challenge.max_attempts,
        "attempt_limit_mode": event.attempt_limit_mode,
        "solved": is_solved,
        "attempt_count": attempt_count,
        "attempts_remaining": attempts_remaining,
        "timeout_retry_after": timeout_retry_after,
        "hints": [
            {
                "id": str(hint.id),
                "order": hint.order,
                "penalty": hint.penalty,
                "unlocked": hint.id in unlocked_ids,
                "text": hint.text if hint.id in unlocked_ids else None,
            }
            for hint in all_hints
        ],
        "next_hint_id": str(next_hint.id) if next_hint is not None else None,
        "next_hint_cost": hint_purchase["next_hint_cost"],
        "points_after_next_hint": hint_purchase["points_after_next_hint"],
        "total_hint_penalty": total_hint_penalty,
        "files": [
            {
                "id": str(challenge_file.id),
                "filename": challenge_file.filename,
                "display_name": challenge_file.display_name,
                "size_bytes": challenge_file.file_size_bytes,
                "content_type": challenge_file.content_type,
            }
            for challenge_file in get_challenge_files(challenge.id)
        ],
        "prerequisites_met": prereqs_met,
        "unmet_prerequisites": [{"id": str(required.id), "name": required.name} for required in unmet],
        "connection_info": resolve_target_connection_info(challenge, participant),
        # CTF-110: a LOCKED challenge is readable but not submittable; the SPA
        # uses this to replace the submit form with a locked notice.
        "locked": challenge.is_visibility_locked,
        "show_solution": show_solution,
        "solution": challenge.solution if show_solution else None,
        "rating": _participant_rating(event, participant, challenge),
    }


def _participant_rating(event: CTFEvent, participant: CTFParticipant, challenge: CTFChallenge) -> dict[str, Any] | None:
    """Return the challenge rating projection for the participant, or None.

    ``None`` when ratings are disabled for the event. The aggregate average and
    count are surfaced only when rating visibility is ``public``; the
    participant's own rating is always included so they can see/adjust it.
    """
    if event.rating_visibility == "disabled":
        return None
    from ctf.models import CTFChallengeRating
    from ctf.services.submission import get_challenge_rating

    own = CTFChallengeRating.objects.filter(participant=participant, challenge=challenge).first()
    public = event.rating_visibility == "public"
    aggregate = get_challenge_rating(challenge.id) if public else {"average": None, "count": 0}
    return {
        "average": aggregate["average"],
        "count": aggregate["count"],
        "own_rating": own.value if own is not None else None,
        "public": public,
    }


def participant_profile(participant: CTFParticipant) -> dict[str, Any]:
    """Event-scoped profile for the me-surface (CTF-610).

    Platform identity (username) appears only for isolated CTF accounts; the
    solve history itself lives on the submissions endpoint.
    """
    from ctf.api.organizer._base import _participant_username

    return {
        "id": str(participant.id),
        "name": participant.name,
        "affiliation": participant.affiliation,
        "email": participant.email,
        "username": _participant_username(participant),
        "role": participant.role,
        "status": participant.status,
        "event": {"id": str(participant.event.id), "name": participant.event.name},
        "score": participant.cached_score,
        "solve_count": participant.cached_solve_count,
    }
