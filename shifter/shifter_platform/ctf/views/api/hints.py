"""Hint-management JSON API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods, require_POST

if TYPE_CHECKING:
    from django.http import HttpRequest


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
)

logger = logging.getLogger(__name__)

_HINT_REQUEST_FAILED = "Could not process hint request."


def _handle_add_hint(request: HttpRequest, challenge_id: UUID, user: User) -> JsonResponse:
    """Add a hint from the POST body, returning a 201 payload or a mapped error."""
    from ctf.exceptions import CTFNotFoundError, CTFPermissionError, CTFStateError, CTFValidationError
    from ctf.services.hint import add_hint

    try:
        body = _parse_body_object(request)
    except _BodyParseError as e:
        return _json_error(e, _HINT_REQUEST_FAILED, 400)

    hint = None
    error: tuple[str, int] | None = None
    try:
        hint = add_hint(challenge_id, body, actor_id=user.pk)
    except CTFPermissionError:
        error = ("Forbidden", 403)
    except (CTFNotFoundError, CTFStateError, CTFValidationError) as e:
        error = _error_tuple(e, _HINT_REQUEST_FAILED, 400)
    if error is not None:
        return JsonResponse({"error": error[0]}, status=error[1])

    assert hint is not None
    return JsonResponse(
        {"id": str(hint.id), "text": hint.text, "penalty": hint.penalty, "order": hint.order},
        status=201,
    )


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def api_challenge_hints(request: HttpRequest, challenge_id: UUID) -> JsonResponse:
    """API: List or add hints for a challenge.

    GET: List all hints for a challenge.
    POST: Add a new hint. Body: {"text": "...", "penalty": 0-100, "order": int}
    """
    from ctf.services.hint import get_hints

    _challenge, error = _resolve_owned_challenge_json(request, challenge_id)
    if error is not None:
        return error
    user = _get_user(request)

    if request.method == "GET":
        hints = get_hints(challenge_id)
        data = [
            {
                "id": str(h.id),
                "text": h.text,
                "penalty": h.penalty,
                "order": h.order,
            }
            for h in hints
        ]
        return JsonResponse({"hints": data})

    return _handle_add_hint(request, challenge_id, user)


@login_required
@ctf_organizer_required
@require_POST
def api_hint_delete(request: HttpRequest, hint_id: UUID) -> JsonResponse:
    """API: Delete a hint."""
    from ctf.exceptions import CTFNotFoundError, CTFPermissionError, CTFStateError
    from ctf.services.hint import remove_hint

    error: tuple[str, int] | None = None
    try:
        remove_hint(hint_id, actor_id=_get_user(request).pk)
    except CTFPermissionError:
        error = ("Forbidden", 403)
    except CTFNotFoundError as e:
        error = _error_tuple(e, "Hint or challenge not found.", 404)
    except CTFStateError as e:
        error = _error_tuple(e, _HINT_REQUEST_FAILED, 400)
    if error is not None:
        return JsonResponse({"error": error[0]}, status=error[1])
    return JsonResponse({}, status=204)
