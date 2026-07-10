"""Shared ownership-resolution and service-delete helpers for the JSON API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.contrib.auth.models import User
from django.http import JsonResponse

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest

    from ctf.models import (
        CTFChallenge,
        CTFEvent,
    )

from ctf.views._access import (
    _check_event_ownership,
    _error_tuple,
    _get_user,
)

logger = logging.getLogger(__name__)


def _resolve_owned_event_json(request: HttpRequest, event_id: UUID) -> tuple[CTFEvent | None, JsonResponse | None]:
    """Resolve an event (404 if missing) and enforce ownership; return (event, error_response)."""
    from ctf.exceptions import CTFNotFoundError
    from ctf.services import get_event

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        return None, JsonResponse({"error": "Event not found"}, status=404)

    if event.created_by_id != request.user.pk:
        return None, JsonResponse({"error": "Forbidden"}, status=403)

    return event, None


def _resolve_owned_challenge_json(
    request: HttpRequest, challenge_id: UUID
) -> tuple[CTFChallenge | None, JsonResponse | None]:
    """Resolve a challenge (404 if missing) and enforce event ownership; return (challenge, error_response)."""
    from ctf.exceptions import CTFNotFoundError
    from ctf.services import get_challenge

    try:
        challenge = get_challenge(challenge_id)
    except CTFNotFoundError:
        return None, JsonResponse({"error": "Challenge not found"}, status=404)

    forbidden = _check_event_ownership(challenge.event, _get_user(request))
    if forbidden:
        return None, forbidden

    return challenge, None


def _delete_via_service_response(action_fn: Callable[..., Any], target_id: UUID, user: User) -> JsonResponse:
    """Run a delete-style service action, returning ``{"success": True}`` or a mapped 4xx error."""
    from ctf.exceptions import CTFNotFoundError, CTFPermissionError, CTFStateError

    error: tuple[str, int] | None = None
    try:
        action_fn(target_id, actor_id=user.pk)
    except CTFPermissionError:
        error = ("Forbidden", 403)
    except CTFNotFoundError as e:
        error = _error_tuple(e, "Resource not found.", 404)
    except CTFStateError as e:
        error = _error_tuple(e, "Invalid request.", 400)
    if error is not None:
        return JsonResponse({"error": error[0]}, status=error[1])
    return JsonResponse({"success": True})
