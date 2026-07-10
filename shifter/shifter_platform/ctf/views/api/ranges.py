"""Range lifecycle JSON API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest


from ctf.views import _access
from ctf.views._access import (
    _check_invite_rate_limit,
    _get_user,
    _json_error,
    _resolve_owned_participant,
    ctf_organizer_required,
    ctf_participant_required,
)
from ctf.views._parsing import (
    _BodyParseError,
    _get_body_str,
    _parse_body_object,
)
from ctf.views.api._common import (
    _resolve_owned_event_json,
)

logger = logging.getLogger(__name__)

_PARTICIPANT_NOT_FOUND_MSG = "Participant not found"
_EVENT_NOT_FOUND_MSG = "Event not found"
_RECOVERY_REQUEST_FAILED_MSG = "Could not process range recovery request."


@login_required
@ctf_participant_required
@require_GET
def api_range_status(request: HttpRequest) -> JsonResponse:
    """API: Get range status for current participant."""
    from ctf.exceptions import CTFNotFoundError
    from ctf.services import range as range_service

    participant = _access._get_active_participant(request)

    if not participant:
        return JsonResponse({"status": "not_assigned", "range_instance_id": None})

    try:
        status = range_service.get_range_status(participant.pk)
        return JsonResponse(status)
    except CTFNotFoundError:
        return JsonResponse({"error": _PARTICIPANT_NOT_FOUND_MSG}, status=404)


@login_required
@ctf_participant_required
@require_POST
def api_range_access(request: HttpRequest) -> JsonResponse:
    """API: Get range access URL.

    Delegates to mission_control's Guacamole RDP endpoint.
    CTF participants are standard users with ranges — the platform's
    existing RDP access flow works for them directly.
    """
    from django.urls import reverse

    return JsonResponse(
        {
            "redirect": reverse("mission_control:guacamole_rdp_url"),
            "message": "Use the mission_control RDP endpoint directly.",
        }
    )


@login_required
@ctf_organizer_required
@require_GET
def api_range_list(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """API: Range status for all participants in an event.

    Args:
        event_id: UUID of the event.
    """
    from ctf.exceptions import CTFNotFoundError
    from ctf.models import CTFParticipant
    from ctf.services import get_event

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        return JsonResponse({"error": _EVENT_NOT_FOUND_MSG}, status=404)

    if event.created_by_id != request.user.pk:
        return JsonResponse({"error": "Forbidden"}, status=403)

    participants = CTFParticipant.objects.filter(event=event).order_by("name")
    data = [
        {
            "participant_id": str(p.pk),
            "name": p.name,
            "email": p.email,
            "range_instance_id": p.range_instance_id,
            "range_status": p.range_status or "not_assigned",
        }
        for p in participants
    ]

    from ctf.services import range as range_service

    progress = range_service.get_provision_progress(event_id)

    return JsonResponse(
        {
            "event_id": str(event_id),
            "ranges": data,
            "progress": progress,
        }
    )


@login_required
@ctf_organizer_required
@require_POST
def api_provision_ranges(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """API: Queue bulk range provisioning for an event.

    Enqueues (or coalesces onto) a background spin-up task and returns
    immediately so the request thread is never blocked by the throttled
    provisioning loop. Progress is polled via ``api_range_list``.

    Args:
        event_id: UUID of the event.
    """
    from ctf.exceptions import CTFNotFoundError
    from ctf.services import get_event

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        return JsonResponse({"error": _EVENT_NOT_FOUND_MSG}, status=404)

    if event.created_by_id != request.user.pk:
        return JsonResponse({"error": "Forbidden"}, status=403)

    from ctf.services import range as range_service

    task = range_service.request_event_provisioning(event_id, source="manual")
    return JsonResponse(
        {
            "event_id": str(event_id),
            "status": "queued",
            "task_id": str(task.pk),
            "task_status": task.status,
        },
        status=202,
    )


@login_required
@ctf_organizer_required
@require_POST
def api_provision_participant_range(request: HttpRequest, participant_id: UUID) -> JsonResponse:
    """API: Provision a range for a single participant."""
    from ctf.services import range as range_service

    return _participant_range_action(request, participant_id, range_service.provision_participant_range)


@login_required
@ctf_organizer_required
@require_POST
def api_destroy_participant_range(request: HttpRequest, participant_id: UUID) -> JsonResponse:
    """API: Destroy a range for a single participant."""
    from ctf.services import range as range_service

    return _participant_range_action(request, participant_id, range_service.destroy_participant_range)


def _run_participant_range_action(participant_id: UUID, action_fn: Callable[[UUID], Any]) -> JsonResponse:
    """Run a range action for a participant, returning its result or a 400 on a known range error."""
    from ctf.exceptions import CTFNotFoundError, CTFRangeError

    try:
        result = action_fn(participant_id)
    except (CTFNotFoundError, CTFRangeError) as e:
        return _json_error(e, "Could not process range request.", 400)
    return JsonResponse(result)


def _participant_range_action(
    request: HttpRequest, participant_id: UUID, action_fn: Callable[[UUID], Any]
) -> JsonResponse:
    """Common logic for organizer range actions (stop, start, restart, etc.)."""
    from ctf.models import CTFParticipant

    try:
        participant = CTFParticipant.objects.select_related("event").get(pk=participant_id)
    except CTFParticipant.DoesNotExist:
        return JsonResponse({"error": _PARTICIPANT_NOT_FOUND_MSG}, status=404)

    if participant.event.created_by_id != request.user.pk:
        return JsonResponse({"error": "Forbidden"}, status=403)

    return _run_participant_range_action(participant_id, action_fn)


@login_required
@ctf_organizer_required
@require_POST
def api_stop_participant_range(request: HttpRequest, participant_id: UUID) -> JsonResponse:
    """API: Stop (pause) a participant's range."""
    from ctf.services import range as range_service

    return _participant_range_action(request, participant_id, range_service.stop_participant_range)


@login_required
@ctf_organizer_required
@require_POST
def api_start_participant_range(request: HttpRequest, participant_id: UUID) -> JsonResponse:
    """API: Start (resume) a participant's stopped range."""
    from ctf.services import range as range_service

    return _participant_range_action(request, participant_id, range_service.start_participant_range)


@login_required
@ctf_organizer_required
@require_POST
def api_restart_participant_range(request: HttpRequest, participant_id: UUID) -> JsonResponse:
    """API: Restart a participant's range."""
    from ctf.services import range as range_service

    return _participant_range_action(request, participant_id, range_service.restart_participant_range)


def _parse_spare_range_instance_id(body: dict[str, Any]) -> int | None:
    """Validate the optional spare-range field as a positive int, else raise `_BodyParseError`.

    Boundary-only validation: the service still validates ``strategy``
    against ``ctf.enums`` and resolves/validates the spare range itself.
    """
    if "spare_range_instance_id" not in body or body["spare_range_instance_id"] is None:
        return None
    value = body["spare_range_instance_id"]
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise _BodyParseError("spare_range_instance_id must be a positive integer")
    return value


def _run_recover_participant_range(request: HttpRequest, participant_id: UUID) -> JsonResponse:
    """Parse the recovery request body, invoke the recovery service, and render the response.

    Split out of :func:`api_recover_participant_range` so each function stays
    within the project's per-function return-count limit.
    """
    from ctf.exceptions import CTFNotFoundError, CTFRangeError, CTFValidationError
    from ctf.services.range import recover_participant_range

    try:
        body = _parse_body_object(request)
        strategy = _get_body_str(body, "strategy", required=True)
        spare_range_instance_id = _parse_spare_range_instance_id(body)
        result = recover_participant_range(
            participant_id,
            strategy=strategy,
            operator=_get_user(request),
            spare_range_instance_id=spare_range_instance_id,
        )
    except _BodyParseError as e:
        response: JsonResponse = _json_error(e, _RECOVERY_REQUEST_FAILED_MSG, 400)
    except CTFNotFoundError as e:
        response = _json_error(e, _PARTICIPANT_NOT_FOUND_MSG, 404)
    except (CTFValidationError, CTFRangeError) as e:
        response = _json_error(e, _RECOVERY_REQUEST_FAILED_MSG, 400)
    else:
        response = JsonResponse(result)

    return response


@login_required
@ctf_organizer_required
@require_POST
def api_recover_participant_range(request: HttpRequest, participant_id: UUID) -> JsonResponse:
    """API: Recover a participant's range that is beyond in-place repair (issue #1018).

    Organizer-only; a participant may not recover their own or anyone else's
    range. POST body: ``{"strategy": "rebuild"|"reassign_spare",
    "spare_range_instance_id": <int, optional>}``. Only these fields are
    read -- scenario/user/status/score are not accepted here. The old range
    is always destroyed; there is no disposition/forensics-retention choice.

    Args:
        participant_id: UUID of the participant whose range is being recovered.
    """
    participant, error = _resolve_owned_participant(request, participant_id)
    if error is not None:
        return error
    assert participant is not None

    return _run_recover_participant_range(request, participant_id)


# Sane operator-facing upper bound on a single top-up request. Large enough for
# any real event's recovery pool, small enough to block a fat-fingered or
# malicious request from queuing an unbounded amount of CMS provisioning work.
_MAX_SPARE_POOL_COUNT = 25


def _parse_spare_pool_count(body: dict[str, Any]) -> int:
    """Validate the required ``count`` field as a bounded non-negative int, else raise `_BodyParseError`."""
    if "count" not in body:
        raise _BodyParseError("count is required")
    value = body["count"]
    if isinstance(value, bool) or not isinstance(value, int):
        raise _BodyParseError("count must be an integer")
    if value < 0:
        raise _BodyParseError("count must be non-negative")
    if value > _MAX_SPARE_POOL_COUNT:
        raise _BodyParseError(f"count must not exceed {_MAX_SPARE_POOL_COUNT}")
    return value


def _run_provision_event_spares(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """Parse the spare-pool top-up body, invoke the provisioning service, and render the response.

    Split out of :func:`api_provision_event_spares` so each function stays
    within the project's per-function return-count limit.
    """
    from ctf.exceptions import CTFNotFoundError
    from ctf.services.range import provision_event_spares

    try:
        body = _parse_body_object(request)
        count = _parse_spare_pool_count(body)
    except _BodyParseError as e:
        return _json_error(e, "Could not process spare pool request.", 400)

    try:
        result = provision_event_spares(event_id, count, operator=_get_user(request))
    except CTFNotFoundError as e:
        return _json_error(e, _EVENT_NOT_FOUND_MSG, 404)

    return JsonResponse(result)


@login_required
@ctf_organizer_required
@require_POST
def api_provision_event_spares(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """API: Set/top-up an event's spare-range recovery pool (issue #1018).

    Organizer-owned-event only. POST body: ``{"count": <non-negative int>}``.
    Tops the pool up to ``count`` (never shrinks existing ranges -- see
    ``provision_event_spares``). Returns the resulting pool summary.

    Args:
        event_id: UUID of the event.
    """
    event, error = _resolve_owned_event_json(request, event_id)
    if error is not None:
        return error
    assert event is not None

    return _run_provision_event_spares(request, event_id)


@login_required
@ctf_organizer_required
@require_POST
def api_send_invitations(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """API: Send invitation emails to all uninvited participants.

    Args:
        event_id: UUID of the event.
    """
    from ctf.services.notification import send_invitations

    if not _check_invite_rate_limit(_get_user(request).pk):
        return JsonResponse({"error": "Too many invitations. Try again later."}, status=429)

    _event, error = _resolve_owned_event_json(request, event_id)
    if error is not None:
        return error

    result = send_invitations(event_id)
    return JsonResponse({"success": True, **result})
