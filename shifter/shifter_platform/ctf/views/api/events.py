"""Event JSON API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_http_methods

if TYPE_CHECKING:
    from django.http import HttpRequest

    from ctf.models import (
        CTFEvent,
    )

from ctf.views._access import (
    _get_user,
    _json_error,
    ctf_organizer_required,
)
from ctf.views._parsing import (
    _BodyParseError,
    _parse_body_object,
)
from ctf.views.api._common import (
    _resolve_owned_event_json,
)

logger = logging.getLogger(__name__)

_INVALID_EVENT_REQUEST = "Invalid event request."


def _handle_event_create_post(request: HttpRequest, user: User) -> JsonResponse:
    """Create an event from the POST body, returning a 201 payload or a 400 error."""
    from ctf.exceptions import CTFValidationError
    from ctf.services import create_event

    try:
        body = _parse_body_object(request)
    except _BodyParseError as e:
        return _json_error(e, _INVALID_EVENT_REQUEST, 400)

    # Parse datetime strings to datetime objects for the service layer
    from django.utils.dateparse import parse_datetime

    for field in ("event_start", "event_end", "registration_deadline"):
        if field in body and isinstance(body[field], str):
            parsed = parse_datetime(body[field])
            if parsed:
                body[field] = parsed

    try:
        event = create_event(user, body)
    except (CTFValidationError, ValidationError) as e:
        # Django model validation (ValidationError) and domain validation both
        # map to a controlled 400; the exception detail is logged, not returned.
        return _json_error(e, _INVALID_EVENT_REQUEST, 400)

    return JsonResponse(
        {
            "id": str(event.id),
            "name": event.name,
            "status": event.status,
        },
        status=201,
    )


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def api_event_list(request: HttpRequest) -> JsonResponse:
    """API: List events or create new event.

    GET: List events for organizer.
    POST: Create new event.
    """
    from ctf.services import get_organizer_events

    user = _get_user(request)

    if request.method == "GET":
        events = get_organizer_events(user)
        data = [
            {
                "id": str(e.id),
                "name": e.name,
                "status": e.status,
                "event_start": e.event_start.isoformat(),
                "event_end": e.event_end.isoformat(),
                "team_mode": e.team_mode,
            }
            for e in events
        ]
        return JsonResponse({"events": data})

    return _handle_event_create_post(request, user)


def _event_detail_payload(event: CTFEvent) -> dict[str, Any]:
    """Render the GET-event JSON payload for `api_event_detail`."""
    return {
        "id": str(event.id),
        "name": event.name,
        "description": event.description,
        "status": event.status,
        "event_start": event.event_start.isoformat(),
        "event_end": event.event_end.isoformat(),
        "registration_deadline": event.registration_deadline.isoformat() if event.registration_deadline else None,
        "scenario_id": event.scenario_id,
        "auto_cleanup": event.auto_cleanup,
        "cleanup_delay_hours": event.cleanup_delay_hours,
        "max_participants": event.max_participants,
        "team_mode": event.team_mode,
        "team_size_limit": event.team_size_limit,
        "range_config": event.range_config,
        "range_spinup_minutes": event.range_spinup_minutes,
        "submission_cooldown_seconds": event.submission_cooldown_seconds,
        "attempt_limit_mode": event.attempt_limit_mode,
        "attempt_limit_cooldown_seconds": event.attempt_limit_cooldown_seconds,
        "rating_visibility": event.rating_visibility,
        "scoring_mode": event.scoring_mode,
        "scoreboard_visible": event.scoreboard_visible,
        "scoreboard_freeze_at": event.scoreboard_freeze_at.isoformat() if event.scoreboard_freeze_at else None,
    }


def _coerce_event_datetime_fields(body: dict[str, Any]) -> None:
    """In-place: parse ISO datetime strings on the four scheduling fields."""
    from django.utils.dateparse import parse_datetime

    for field in ("event_start", "event_end", "registration_deadline", "scoreboard_freeze_at"):
        if field in body and isinstance(body[field], str):
            parsed = parse_datetime(body[field])
            if parsed:
                body[field] = parsed


def _handle_event_update_put(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """Update an event from the PUT body, returning the updated payload or a 400 error."""
    from ctf.exceptions import CTFStateError, CTFValidationError
    from ctf.services import update_event

    try:
        body = _parse_body_object(request)
    except _BodyParseError as e:
        return _json_error(e, _INVALID_EVENT_REQUEST, 400)
    _coerce_event_datetime_fields(body)

    try:
        updated = update_event(event_id, body)
    except (CTFValidationError, CTFStateError, ValidationError) as e:
        return _json_error(e, _INVALID_EVENT_REQUEST, 400)

    return JsonResponse(
        {
            "id": str(updated.id),
            "name": updated.name,
            "status": updated.status,
        }
    )


def _dispatch_event_detail_method(request: HttpRequest, event: CTFEvent, event_id: UUID) -> JsonResponse:
    """Dispatch GET/DELETE/PUT for an already-resolved, owned event."""
    if request.method == "GET":
        return JsonResponse(_event_detail_payload(event))

    if request.method == "DELETE":
        from ctf.services import delete_event

        delete_event(event_id)
        return JsonResponse({}, status=204)

    return _handle_event_update_put(request, event_id)


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "PUT", "DELETE"])
def api_event_detail(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """API: Get, update, or delete event.

    Args:
        event_id: UUID of the event.
    """
    event, error = _resolve_owned_event_json(request, event_id)
    if error is not None:
        return error
    assert event is not None
    return _dispatch_event_detail_method(request, event, event_id)


def _force_delete_event_response(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """Validate the confirmation name and force-delete the event, returning the result or a 400 error."""
    from ctf.exceptions import CTFValidationError
    from ctf.services import force_delete_event

    try:
        body = _parse_body_object(request)
        confirmation_name = body.get("confirmation_name")
        if not confirmation_name:
            raise _BodyParseError("confirmation_name is required")
    except _BodyParseError as e:
        return _json_error(e, "confirmation_name is required.", 400)

    user = _get_user(request)
    try:
        result = force_delete_event(event_id, user, confirmation_name)
    except CTFValidationError as e:
        return _json_error(e, _INVALID_EVENT_REQUEST, 400)

    return JsonResponse(result)


@login_required
@ctf_organizer_required
@require_http_methods(["POST"])
def api_force_delete_event(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """API: Force-delete an event and all associated resources.

    POST body: {"confirmation_name": "<exact event name>"}

    Args:
        event_id: UUID of the event.
    """
    from ctf.models import CTFEvent

    try:
        event = CTFEvent.all_objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        return JsonResponse({"error": "Event not found"}, status=404)

    if event.created_by_id != request.user.pk:
        return JsonResponse({"error": "Forbidden"}, status=403)

    return _force_delete_event_response(request, event_id)


@login_required
@ctf_organizer_required
@require_GET
def api_scenarios(request: HttpRequest) -> JsonResponse:
    """API: List available scenarios for CTF events.

    Returns a list of scenario id/name pairs from the CMS registry.
    """
    from ctf.bridges import cms_list_scenarios

    user = _get_user(request)
    scenarios = [{"id": sid, "name": name} for sid, name in cms_list_scenarios(user)]
    return JsonResponse({"scenarios": scenarios})
