"""Challenge CRUD JSON API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

if TYPE_CHECKING:
    from django.http import HttpRequest

    from ctf.models import (
        CTFChallenge,
    )

from ctf.views._access import (
    _error_tuple,
    _get_user,
    _json_error,
    ctf_organizer_required,
)
from ctf.views._parsing import (
    _BodyParseError,
    _parse_body_object,
)
from ctf.views.api._common import (
    _resolve_owned_challenge_json,
    _resolve_owned_event_json,
)

logger = logging.getLogger(__name__)

_INVALID_CHALLENGE_REQUEST = "Invalid challenge request."


def _challenge_list_get(event_id: UUID, user: User) -> JsonResponse:
    """List challenges for an event as JSON, or 403 when the actor lacks access."""
    from ctf.exceptions import CTFPermissionError
    from ctf.services import list_challenges_for_event

    try:
        challenges = list_challenges_for_event(event_id, actor_id=user.pk).prefetch_related("tags", "topics")
    except CTFPermissionError:
        return JsonResponse({"error": "Forbidden"}, status=403)
    data = [
        {
            "id": str(c.id),
            "name": c.name,
            "category": c.category,
            "points": c.points,
            "difficulty": c.difficulty,
            "order": c.order,
            "tags": list(c.tags.values_list("name", flat=True)),
            "topics": list(c.topics.values_list("name", flat=True)),
        }
        for c in challenges
    ]
    return JsonResponse({"challenges": data})


def _handle_challenge_create_api_post(request: HttpRequest, event_id: UUID, user: User) -> JsonResponse:
    """Create a challenge from the POST body, returning a 201 payload or an error."""
    from ctf.exceptions import CTFNotFoundError, CTFPermissionError, CTFStateError, CTFValidationError
    from ctf.services import create_challenge

    try:
        body = _parse_body_object(request)
    except _BodyParseError as e:
        return _json_error(e, _INVALID_CHALLENGE_REQUEST, 400)

    challenge = None
    error: tuple[str, int] | None = None
    try:
        challenge = create_challenge(event_id, body, actor_id=user.pk)
    except CTFPermissionError:
        error = ("Forbidden", 403)
    except CTFNotFoundError as e:
        error = _error_tuple(e, "Challenge not found.", 404)
    except (CTFValidationError, CTFStateError) as e:
        error = _error_tuple(e, _INVALID_CHALLENGE_REQUEST, 400)
    if error is not None:
        return JsonResponse({"error": error[0]}, status=error[1])

    assert challenge is not None
    return JsonResponse(
        {
            "id": str(challenge.id),
            "name": challenge.name,
            "category": challenge.category,
            "points": challenge.points,
        },
        status=201,
    )


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def api_challenge_list(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """API: List challenges or create new challenge.

    Args:
        event_id: UUID of the event.
    """
    _event, error = _resolve_owned_event_json(request, event_id)
    if error is not None:
        return error

    user = _get_user(request)
    if request.method == "GET":
        return _challenge_list_get(event_id, user)
    return _handle_challenge_create_api_post(request, event_id, user)


def _challenge_detail_payload(challenge: CTFChallenge) -> dict[str, Any]:
    """Render the GET-challenge JSON payload for `api_challenge_detail`."""
    return {
        "id": str(challenge.id),
        "name": challenge.name,
        "description": challenge.description,
        "category": challenge.category,
        "points": challenge.points,
        "difficulty": challenge.difficulty,
        "flag_format": challenge.flag_format,
        "hints": [
            {"id": str(h.id), "text": h.text, "penalty": h.penalty, "order": h.order} for h in challenge.hints.all()
        ],
        "max_attempts": challenge.max_attempts,
        "order": challenge.order,
        "release_time": challenge.release_time.isoformat() if challenge.release_time else None,
        "tags": list(challenge.tags.values_list("name", flat=True)),
        "topics": list(challenge.topics.values_list("name", flat=True)),
        "solution": challenge.solution,
    }


def _handle_challenge_delete(challenge_id: UUID, user: User) -> JsonResponse:
    """Delete a challenge, returning 204 or an error."""
    from ctf.exceptions import CTFNotFoundError, CTFPermissionError, CTFStateError
    from ctf.services import delete_challenge

    try:
        delete_challenge(challenge_id, actor_id=user.pk)
    except CTFPermissionError:
        return JsonResponse({"error": "Forbidden"}, status=403)
    except (CTFNotFoundError, CTFStateError) as e:
        return _json_error(e, _INVALID_CHALLENGE_REQUEST, 400)
    return JsonResponse({}, status=204)


def _handle_challenge_update_put(request: HttpRequest, challenge_id: UUID, user: User) -> JsonResponse:
    """Update a challenge from the PUT body, returning the updated payload or an error."""
    from ctf.exceptions import CTFNotFoundError, CTFPermissionError, CTFStateError, CTFValidationError
    from ctf.services import update_challenge

    try:
        body = _parse_body_object(request)
    except _BodyParseError as e:
        return _json_error(e, _INVALID_CHALLENGE_REQUEST, 400)

    updated = None
    error: tuple[str, int] | None = None
    try:
        updated = update_challenge(challenge_id, body, actor_id=user.pk)
    except CTFPermissionError:
        error = ("Forbidden", 403)
    except (CTFNotFoundError, CTFValidationError, CTFStateError) as e:
        error = _error_tuple(e, _INVALID_CHALLENGE_REQUEST, 400)
    if error is not None:
        return JsonResponse({"error": error[0]}, status=error[1])

    assert updated is not None
    return JsonResponse(
        {
            "id": str(updated.id),
            "name": updated.name,
            "category": updated.category,
            "points": updated.points,
        }
    )


def _dispatch_challenge_detail_method(
    request: HttpRequest, challenge: CTFChallenge, challenge_id: UUID, user: User
) -> JsonResponse:
    """Dispatch GET/DELETE/PUT for an already-resolved, owned challenge."""
    if request.method == "GET":
        return JsonResponse(_challenge_detail_payload(challenge))
    if request.method == "DELETE":
        return _handle_challenge_delete(challenge_id, user)
    return _handle_challenge_update_put(request, challenge_id, user)


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "PUT", "DELETE"])
def api_challenge_detail(request: HttpRequest, challenge_id: UUID) -> JsonResponse:
    """API: Get, update, or delete challenge.

    Args:
        challenge_id: UUID of the challenge.
    """
    challenge, error = _resolve_owned_challenge_json(request, challenge_id)
    if error is not None:
        return error
    assert challenge is not None
    return _dispatch_challenge_detail_method(request, challenge, challenge_id, _get_user(request))
