"""Participant challenge-interaction JSON API (submit, hint, rate, submissions)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from risk_register.services import get_client_ip
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from django.http import HttpRequest

    from ctf.models import (
        CTFParticipant,
    )

from ctf.views import _access
from ctf.views._access import (
    _json_error,
    ctf_participant_required,
)
from ctf.views._parsing import (
    _BodyParseError,
    _BodyUUIDError,
    _get_body_str,
    _parse_body_object,
    _parse_body_uuid,
)

logger = logging.getLogger(__name__)

_CHALLENGE_OR_PARTICIPANT_NOT_FOUND = "Challenge or participant not found."
_CHALLENGE_ACTION_FAILED = "Could not process challenge action."


def _resolve_challenge_participant(
    request: HttpRequest, challenge_id: UUID
) -> tuple[CTFParticipant | None, JsonResponse | None]:
    """Resolve a challenge (404) then the request's participant scoped to its event (403)."""
    from ctf.exceptions import CTFNotFoundError
    from ctf.services.challenge import get_challenge

    # Resolve the participant scoped to THIS challenge's event (codex cycle 4).
    try:
        challenge = get_challenge(challenge_id)
    except CTFNotFoundError:
        return None, JsonResponse({"error": "Challenge not found"}, status=404)
    participant = _access._get_participant_for_challenge(request, challenge)
    if not participant:
        return None, JsonResponse({"error": "Forbidden"}, status=403)
    return participant, None


def _submit_flag_response(
    participant: CTFParticipant, challenge_id: UUID, flag: str, ip_address: str | None
) -> JsonResponse:
    """Submit the flag and return the scored result, or a 4xx/429 error response."""
    from ctf.exceptions import CTFNotFoundError, CTFRateLimitError, CTFStateError, CTFValidationError
    from ctf.services.scoring import calculate_score, get_participant_rank
    from ctf.services.submission import submit_flag

    submission = None
    error_resp = None
    try:
        submission = submit_flag(participant.id, challenge_id, flag, ip_address=ip_address)
    except CTFNotFoundError as e:
        error_resp = _json_error(e, _CHALLENGE_OR_PARTICIPANT_NOT_FOUND, 404)
    except (CTFValidationError, CTFStateError) as e:
        error_resp = _json_error(e, _CHALLENGE_ACTION_FAILED, 400)
    except CTFRateLimitError as e:
        retry_after = e.details.get("retry_after_seconds")
        logger.warning("CTF API error (429): Rate limit exceeded. | %s", safe_log_value(str(e)))
        payload: dict[str, Any] = {"error": "Rate limit exceeded."}
        if retry_after is not None:
            payload["retry_after_seconds"] = int(retry_after)
        retry_at = e.details.get("retry_at")
        if retry_at:
            payload["retry_at"] = retry_at
        error_resp = JsonResponse(payload, status=429)
        if retry_after:
            error_resp["Retry-After"] = str(int(retry_after))
    if error_resp is not None:
        return error_resp

    assert submission is not None
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


@login_required
@ctf_participant_required
@require_POST
def api_submit_flag(request: HttpRequest, challenge_id: UUID) -> JsonResponse:
    """API: Submit flag for a challenge.

    Args:
        challenge_id: UUID of the challenge.
    """
    participant, error = _resolve_challenge_participant(request, challenge_id)
    if error is not None:
        return error
    assert participant is not None

    try:
        body = _parse_body_object(request)
        flag = _get_body_str(body, "flag").strip()
        if not flag:
            raise _BodyParseError("Flag is required")
    except _BodyParseError as e:
        return _json_error(e, _CHALLENGE_ACTION_FAILED, 400)

    return _submit_flag_response(participant, challenge_id, flag, get_client_ip(request))


def _unlock_hint_response(participant: CTFParticipant, challenge_id: UUID, hint_uuid: UUID) -> JsonResponse:
    """Unlock the given hint, returning the result payload or a 4xx error."""
    from ctf.exceptions import CTFNotFoundError, CTFStateError, CTFValidationError
    from ctf.services.hint import use_hint

    try:
        result = use_hint(participant.id, hint_uuid, expected_challenge_id=challenge_id)
    except CTFNotFoundError as e:
        return _json_error(e, _CHALLENGE_OR_PARTICIPANT_NOT_FOUND, 404)
    except (CTFValidationError, CTFStateError) as e:
        return _json_error(e, _CHALLENGE_ACTION_FAILED, 400)
    return JsonResponse(result)


@login_required
@ctf_participant_required
@require_POST
def api_use_hint(request: HttpRequest, challenge_id: UUID) -> JsonResponse:
    """API: Unlock the next hint for a challenge (or a specific hint by ID).

    POST body (optional): {"hint_id": "<uuid>"}
    If no hint_id provided, unlocks the next hint in order.

    Args:
        challenge_id: UUID of the challenge.
    """
    participant, error = _resolve_challenge_participant(request, challenge_id)
    if error is not None:
        return error
    assert participant is not None

    # Resolve which hint to unlock from the request body. The helper
    # returns either a UUID to unlock or a JsonResponse to return as-is
    # (empty-body → next hint; explicit-but-malformed → 400; no remaining
    # hints → 400). Keeping this out of the main body keeps the cognitive
    # complexity below SonarCloud's threshold.
    hint_uuid_or_response = _resolve_hint_to_unlock(request, participant, challenge_id)
    if isinstance(hint_uuid_or_response, JsonResponse):
        return hint_uuid_or_response

    return _unlock_hint_response(participant, challenge_id, hint_uuid_or_response)


def _rate_challenge_response(participant: CTFParticipant, challenge_id: UUID, value: int) -> JsonResponse:
    """Record the rating, returning the value payload or a 4xx error."""
    from ctf.exceptions import CTFNotFoundError, CTFValidationError
    from ctf.services.submission import rate_challenge

    try:
        rating = rate_challenge(participant.id, challenge_id, value)
    except CTFNotFoundError as e:
        return _json_error(e, _CHALLENGE_OR_PARTICIPANT_NOT_FOUND, 404)
    except CTFValidationError as e:
        return _json_error(e, _CHALLENGE_ACTION_FAILED, 400)
    return JsonResponse({"value": rating.value, "challenge_id": str(challenge_id)})


@login_required
@ctf_participant_required
@require_POST
def api_rate_challenge(request: HttpRequest, challenge_id: UUID) -> JsonResponse:
    """API: Rate a challenge (1-5). Participant must have solved it.

    Args:
        challenge_id: UUID of the challenge.
    """
    participant, error = _resolve_challenge_participant(request, challenge_id)
    if error is not None:
        return error
    assert participant is not None

    try:
        body = _parse_body_object(request)
        value = body.get("value")
        if not isinstance(value, int):
            raise _BodyParseError("value must be an integer (1-5)")
    except _BodyParseError as e:
        return _json_error(e, _CHALLENGE_ACTION_FAILED, 400)

    return _rate_challenge_response(participant, challenge_id, value)


@login_required
@ctf_participant_required
@require_GET
def api_submissions(request: HttpRequest) -> JsonResponse:
    """API: Get submissions for current user."""
    from ctf.services.submission import get_participant_submissions

    participant = _access._get_active_participant(request)
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
            "attempt_number": s.attempt_number,
            "submitted_at": s.submitted_at.isoformat() if s.submitted_at else None,
        }
        for s in submissions.select_related("challenge")
    ]
    return JsonResponse({"submissions": data, "total": len(data)})


def _parse_explicit_hint_id(body: dict[str, Any]) -> UUID | JsonResponse:
    """Parse an explicit `hint_id` body field, returning the UUID or a 400 JsonResponse."""
    try:
        return _parse_body_uuid(body.get("hint_id"), "hint_id")
    except _BodyUUIDError as e:
        return _json_error(e, _CHALLENGE_ACTION_FAILED, 400)


def _resolve_next_unlockable_hint(participant: CTFParticipant, challenge_id: UUID) -> UUID | JsonResponse:
    """Return the UUID of the first not-yet-unlocked hint, or a 400 JsonResponse when none remain."""
    from ctf.services.hint import get_hints, get_unlocked_hints

    unlocked_ids = {h.id for h in get_unlocked_hints(participant.id, challenge_id)}
    next_hint = next((h for h in get_hints(challenge_id) if h.id not in unlocked_ids), None)
    if not next_hint:
        return JsonResponse({"error": "No more hints available"}, status=400)
    return next_hint.id


def _resolve_hint_to_unlock(
    request: HttpRequest, participant: CTFParticipant, challenge_id: UUID
) -> UUID | JsonResponse:
    """Resolve which hint UUID to unlock for `api_use_hint`.

    Returns either a `UUID` (the hint to unlock) or a `JsonResponse` that
    the caller should return as-is. Keeps `api_use_hint` below the
    SonarCloud cognitive-complexity threshold (python:S3776).

    Distinguishes three caller intents:
      - empty body / `{}` → caller wants the next-hint default path;
        returns the UUID of the first not-yet-unlocked hint, or 400 when
        none remain.
      - body explicitly contains `hint_id` (any value, including
        `null`/`""`/malformed) → returns the parsed UUID, or 400 instead
        of silently falling back to the next-hint path.
      - JSON parse failure / non-object body → 400.
    """
    try:
        body = _parse_body_object(request, allow_empty=True)
    except _BodyParseError as e:
        return _json_error(e, _CHALLENGE_ACTION_FAILED, 400)
    if "hint_id" in body:
        return _parse_explicit_hint_id(body)
    return _resolve_next_unlockable_hint(participant, challenge_id)
