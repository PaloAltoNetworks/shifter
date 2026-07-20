"""Challenge-prerequisite JSON API."""

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
    _check_event_ownership,
    _error_tuple,
    _get_user,
    _json_error,
    ctf_organizer_required,
)
from ctf.views._parsing import (
    _BodyParseError,
    _BodyUUIDError,
    _parse_body_object,
    _parse_body_uuid,
)
from ctf.views.api._common import (
    _delete_via_service_response,
    _resolve_owned_challenge_json,
)

logger = logging.getLogger(__name__)


def _handle_add_prerequisite(request: HttpRequest, challenge_id: UUID, user: User) -> JsonResponse:
    """Add a prerequisite from the POST body, returning a 201 payload or a mapped error."""
    from ctf.exceptions import CTFNotFoundError, CTFPermissionError, CTFStateError, CTFValidationError
    from ctf.services.challenge import add_prerequisite

    try:
        body = _parse_body_object(request)
        required_uuid = _parse_body_uuid(body.get("required_challenge_id"), "required_challenge_id")
    except (_BodyParseError, _BodyUUIDError) as e:
        return _json_error(e, "Invalid prerequisite request.", 400)

    prereq = None
    error: tuple[str, int] | None = None
    try:
        prereq = add_prerequisite(challenge_id, required_uuid, actor_id=user.pk)
    except CTFPermissionError:
        error = ("Forbidden", 403)
    except CTFNotFoundError as e:
        error = _error_tuple(e, "Challenge not found.", 404)
    except (CTFStateError, CTFValidationError) as e:
        error = _error_tuple(e, "Invalid prerequisite request.", 400)
    if error is not None:
        return JsonResponse({"error": error[0]}, status=error[1])

    assert prereq is not None
    return JsonResponse(
        {
            "id": str(prereq.id),
            "required_challenge_id": str(prereq.required_challenge_id),
            "required_challenge_name": prereq.required_challenge.name,
        },
        status=201,
    )


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def api_challenge_prerequisites(request: HttpRequest, challenge_id: UUID) -> JsonResponse:
    """API: List and add challenge prerequisites.

    GET: List prerequisites for a challenge.
    POST: Add a prerequisite to a challenge.
    """
    from ctf.services.challenge import get_prerequisites

    _challenge, error = _resolve_owned_challenge_json(request, challenge_id)
    if error is not None:
        return error
    user = _get_user(request)

    if request.method == "GET":
        prereqs = get_prerequisites(challenge_id)
        return JsonResponse(
            {
                "prerequisites": [
                    {
                        "id": str(p.id),
                        "required_challenge_id": str(p.required_challenge_id),
                        "required_challenge_name": p.required_challenge.name,
                        "required_challenge_category": p.required_challenge.category,
                        "required_challenge_points": p.required_challenge.points,
                    }
                    for p in prereqs
                ]
            }
        )

    return _handle_add_prerequisite(request, challenge_id, user)


@login_required
@ctf_organizer_required
@require_POST
def api_prerequisite_delete(request: HttpRequest, prerequisite_id: UUID) -> JsonResponse:
    """API: Remove a prerequisite.

    Args:
        prerequisite_id: UUID of the prerequisite to remove.
    """
    from ctf.models import CTFChallengePrerequisite
    from ctf.services.challenge import remove_prerequisite

    try:
        prereq = CTFChallengePrerequisite.objects.select_related("challenge__event").get(pk=prerequisite_id)
    except CTFChallengePrerequisite.DoesNotExist:
        return JsonResponse({"error": "Prerequisite not found"}, status=404)

    user = _get_user(request)
    forbidden = _check_event_ownership(prereq.challenge.event, user)
    if forbidden:
        return forbidden

    return _delete_via_service_response(remove_prerequisite, prerequisite_id, user)
