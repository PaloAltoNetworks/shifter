"""Access control: role decorators, user/participant resolution, event/participant ownership."""

from __future__ import annotations

import functools
import logging
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from django.contrib.auth.models import User
from django.http import HttpResponse, JsonResponse

from ctf.bridges import get_user_role
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest

    from ctf.models import (
        CTFChallenge,
        CTFEvent,
        CTFParticipant,
    )

logger = logging.getLogger(__name__)


def _check_invite_rate_limit(user_id: int, limit: int = 50, window: int = 3600) -> bool:
    """Return True if within rate limit for magic link generation.

    Uses Django's cache with a fixed-window counter. Default: 50 per hour.
    Note: with the default LocMemCache, limits are per-process. For cross-worker
    enforcement, configure a shared CACHES backend (e.g. Redis, Memcached).
    """
    from django.core.cache import cache

    key = f"invite_ratelimit:{user_id}"
    # add() only sets if key doesn't exist — preserves the original TTL
    cache.add(key, 0, timeout=window)
    try:
        count = cache.incr(key)
    except ValueError:
        # Key expired between add and incr — retry
        cache.set(key, 1, timeout=window)
        count = 1
    return count <= limit


def _get_user(request: HttpRequest) -> User:
    """Get authenticated user from request. Use only in @login_required views."""
    assert request.user.is_authenticated, "View must use @login_required"
    return cast(User, request.user)


def ctf_organizer_required(view_func: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """Decorator that requires the user to be a CTF organizer.

    Returns 403 Forbidden if user is not an organizer.
    Must be used after @login_required.
    """

    @functools.wraps(view_func)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Enforce CTF-organizer access before delegating to the wrapped view."""
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


def ctf_participant_required(view_func: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """Decorator that requires the user to be a registered CTF participant.

    Checks the CTFParticipant table directly — works regardless of
    UserProfile.user_type, so organizers and standard users who are
    also participants aren't blocked.
    """

    @functools.wraps(view_func)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Enforce active-CTF-participant access before delegating to the wrapped view."""
        from ctf.services.participant import is_active_participant

        user = _get_user(request)
        # Issue #768 (codex review class finding): use the playing-status
        # predicate; a row with `registered_at` set but `status=DISQUALIFIED`
        # must NOT pass — scoring excludes those rows from rankings, so any
        # gate that admits them is admitting users to surfaces the scoring
        # view treats as non-existent.
        if not is_active_participant(user):
            logger.warning(
                "CTF participant access denied for user %s",
                user.email,
            )
            return HttpResponse("Forbidden: CTF participant access required", status=403)
        return view_func(request, *args, **kwargs)

    return wrapper


def ctf_role_required(view_func: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """Decorator that requires the user to be a CTF organizer or participant.

    Returns 403 Forbidden if user has no CTF role.
    Must be used after @login_required.
    """

    @functools.wraps(view_func)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Enforce any-CTF-role access before delegating to the wrapped view."""
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


def _check_event_ownership(event: CTFEvent, user: User) -> JsonResponse | None:
    """Return a 403 JsonResponse if the user does not own the event, else None."""
    if event.created_by_id != user.pk:
        return JsonResponse({"error": "Forbidden"}, status=403)
    return None


def _get_active_participant(request: HttpRequest) -> CTFParticipant | None:
    """Resolve the participant for the user's active CTF event.

    Codex review (issue #765/#768/#769) cycle 4: profile-scoped participant
    views (dashboard, event, challenges, range, scoreboard, team) MUST
    resolve the participant scoped to the user's `active_ctf_event_id`
    rather than relying on the unscoped first-row return from
    `get_participant_by_user`. Otherwise a user registered in events A
    and B can wind up acting as the wrong participant when their first
    row belongs to a different event than the active one.
    """
    from ctf.bridges import get_user_role
    from ctf.services.participant import get_participant_by_user

    user = _get_user(request)
    role = get_user_role(user)
    if role.active_ctf_event is None:
        return None
    return get_participant_by_user(user, event_id=role.active_ctf_event.id)


def _get_participant_for_challenge(request: HttpRequest, challenge: CTFChallenge) -> CTFParticipant | None:
    """Resolve the participant for a challenge-scoped request.

    Codex review (issue #765/#768/#769) cycle 4: challenge-scoped views
    (`api_submit_flag`, `api_use_hint`, `api_rate_challenge`,
    `challenge_detail`) MUST scope participant resolution to the
    challenge's event. A multi-event user whose first participant row
    belongs to a different event would otherwise be denied a valid
    submission, or worse, act as an ineligible row in a different event.
    """
    from ctf.services.participant import get_participant_by_user

    return get_participant_by_user(_get_user(request), event_id=challenge.event_id)


def _resolve_owned_participant(
    request: HttpRequest, participant_id: UUID
) -> tuple[CTFParticipant | None, JsonResponse | None]:
    """Resolve a participant and enforce event ownership; return (participant, error_response)."""
    from ctf.exceptions import CTFNotFoundError
    from ctf.services import get_participant

    try:
        participant = get_participant(participant_id)
    except CTFNotFoundError:
        return None, JsonResponse({"error": "Participant not found"}, status=404)

    if participant.event.created_by_id != request.user.pk:
        return None, JsonResponse({"error": "Forbidden"}, status=403)

    return participant, None


def _json_error(exc: Exception, message: str, status: int) -> JsonResponse:
    """Return a JSON error envelope with a controlled, caller-supplied message.

    The underlying exception is logged server-side (sanitised) rather than
    serialised into the response, so internal details never reach the client
    (CWE-209 / py:stack-trace-exposure). The CTF JSON API contract asserts on
    status codes, not response text, so the controlled messages preserve it.
    """
    logger.warning("CTF API error (%s): %s | %s", status, message, safe_log_value(str(exc)))
    return JsonResponse({"error": message}, status=status)


def _error_tuple(exc: Exception, message: str, status: int) -> tuple[str, int]:
    """(message, status) variant of `_json_error` for helpers that defer response
    construction. Logs `exc` server-side and returns a controlled message so the
    exception text never reaches the client (CWE-209 / py:stack-trace-exposure).
    """
    logger.warning("CTF API error (%s): %s | %s", status, message, safe_log_value(str(exc)))
    return message, status
