"""Flag-management JSON API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.views.decorators.http import require_POST

if TYPE_CHECKING:
    from django.http import HttpRequest


from ctf.views._access import (
    _check_event_ownership,
    _error_tuple,
    _get_user,
    _json_error,
    ctf_organizer_required,
)
from ctf.views._parsing import (
    _BodyParseError,
    _get_body_str,
    _parse_body_object,
)
from ctf.views.api._common import (
    _delete_via_service_response,
    _resolve_owned_challenge_json,
)

logger = logging.getLogger(__name__)


def _handle_add_flag(request: HttpRequest, challenge_id: UUID, user: User) -> JsonResponse:
    """Add a flag from the POST body, returning a 201 payload or a mapped error."""
    from ctf.exceptions import CTFNotFoundError, CTFPermissionError, CTFStateError, CTFValidationError
    from ctf.services.challenge import add_flag

    try:
        body = _parse_body_object(request)
        flag_value = _get_body_str(body, "flag").strip()
        flag_type = body.get("flag_type", "static")
        # Flag value is only required for static and regex types
        if flag_type in ("static", "regex") and not flag_value:
            raise _BodyParseError("Flag value is required")
    except _BodyParseError as e:
        return _json_error(e, "Invalid flag request.", 400)

    flag_data = {
        "flag": flag_value,
        "flag_type": flag_type,
        "case_sensitive": body.get("case_sensitive", True),
        "order": body.get("order", 0),
        "validator_config": body.get("validator_config"),
    }

    flag_obj = None
    error: tuple[str, int] | None = None
    try:
        flag_obj = add_flag(challenge_id, flag_data, actor_id=user.pk)
    except CTFPermissionError:
        error = ("Forbidden", 403)
    except CTFNotFoundError as e:
        error = _error_tuple(e, "Flag or challenge not found.", 404)
    except (CTFStateError, CTFValidationError) as e:
        error = _error_tuple(e, "Invalid flag request.", 400)
    if error is not None:
        return JsonResponse({"error": error[0]}, status=error[1])

    assert flag_obj is not None
    response_data: dict[str, Any] = {
        "id": str(flag_obj.id),
        "flag_type": flag_obj.flag_type,
        "case_sensitive": flag_obj.case_sensitive,
        "order": flag_obj.order,
    }
    if flag_obj.validator_config:
        response_data["validator_config"] = flag_obj.validator_config
    return JsonResponse(response_data, status=201)


@login_required
@ctf_organizer_required
@require_POST
def api_add_flag(request: HttpRequest, challenge_id: UUID) -> JsonResponse:
    """API: Add a flag to a challenge.

    Args:
        challenge_id: UUID of the challenge.
    """
    _challenge, error = _resolve_owned_challenge_json(request, challenge_id)
    if error is not None:
        return error

    return _handle_add_flag(request, challenge_id, _get_user(request))


@login_required
@ctf_organizer_required
@require_POST
def api_remove_flag(request: HttpRequest, flag_id: UUID) -> JsonResponse:
    """API: Remove a flag from a challenge.

    Args:
        flag_id: UUID of the flag.
    """
    from ctf.models import CTFFlag
    from ctf.services.challenge import remove_flag

    try:
        flag_obj = CTFFlag.objects.select_related("challenge__event").get(pk=flag_id)
    except CTFFlag.DoesNotExist:
        return JsonResponse({"error": "Flag not found"}, status=404)

    user = _get_user(request)
    forbidden = _check_event_ownership(flag_obj.challenge.event, user)
    if forbidden:
        return forbidden

    return _delete_via_service_response(remove_flag, flag_id, user)
