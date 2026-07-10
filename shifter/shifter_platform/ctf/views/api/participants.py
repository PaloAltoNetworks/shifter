"""Participant-management JSON API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods, require_POST

from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from django.http import HttpRequest

    from ctf.models import (
        CTFParticipant,
    )

from ctf.views._access import (
    _check_invite_rate_limit,
    _get_user,
    _json_error,
    _resolve_owned_participant,
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

_INVALID_PARTICIPANT_REQUEST = "Invalid participant request."


def _participant_list_get(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """Return the JSON participant list for an event, optionally filtered by status."""
    from ctf.services import list_participants_for_event

    participants = list_participants_for_event(event_id)
    status_filter = request.GET.get("status")
    if status_filter:
        participants = participants.filter(status=status_filter)

    data = [
        {
            "id": str(p.id),
            "name": p.name,
            "email": p.email,
            "status": p.status,
            "team_name": p.team.name if p.team else None,
            "registered_at": p.registered_at.isoformat() if p.registered_at else None,
            "total_score": p.total_score,
        }
        for p in participants
    ]
    return JsonResponse({"participants": data, "total": len(data)})


def _handle_participant_invite_post(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """Invite a single participant from the POST body, returning a 201 payload or a 400 error."""
    from ctf.exceptions import CTFValidationError
    from ctf.services import invite_participant

    try:
        body = _parse_body_object(request)
        name = body.get("name")
        email = body.get("email")
        if not name or not email:
            raise _BodyParseError("name and email are required")
    except _BodyParseError as e:
        return _json_error(e, _INVALID_PARTICIPANT_REQUEST, 400)

    try:
        participant = invite_participant(event_id, email, name)
    except CTFValidationError as e:
        return _json_error(e, _INVALID_PARTICIPANT_REQUEST, 400)

    return JsonResponse(
        {
            "id": str(participant.id),
            "name": participant.name,
            "email": participant.email,
            "status": participant.status,
            "invited": True,
        },
        status=201,
    )


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def api_participant_list(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """API: List participants or add new participant.

    GET: Return JSON list of participants.
    POST: Create a new participant.

    Args:
        event_id: UUID of the event.
    """
    _event, error = _resolve_owned_event_json(request, event_id)
    if error is not None:
        return error

    if request.method == "GET":
        return _participant_list_get(request, event_id)
    return _handle_participant_invite_post(request, event_id)


@login_required
@ctf_organizer_required
@require_POST
def api_participant_import(request: HttpRequest, event_id: UUID) -> JsonResponse:
    """API: Bulk import participants from JSON.

    Expects JSON body with "participants" array containing objects with
    "name" and "email" fields.

    Args:
        event_id: UUID of the event.
    """
    from ctf.exceptions import CTFValidationError
    from ctf.services import invite_participant

    _event, error = _resolve_owned_event_json(request, event_id)
    if error is not None:
        return error

    try:
        body = _parse_body_object(request)
        participants_data = body.get("participants", [])
        if not isinstance(participants_data, list):
            raise _BodyParseError("participants must be an array")
    except _BodyParseError as e:
        return _json_error(e, _INVALID_PARTICIPANT_REQUEST, 400)

    imported = []
    errors = []

    for idx, p_data in enumerate(participants_data):
        # Each element must be an object; a bare scalar (e.g. {"participants":
        # ["x"]}) passed the list guard above but would raise AttributeError on
        # .get() and surface as a 500 (#1149). Report it per-item instead.
        if not isinstance(p_data, dict):
            errors.append({"index": idx, "error": "each participant must be an object"})
            continue

        name = p_data.get("name")
        email = p_data.get("email")

        if not name or not email:
            errors.append({"index": idx, "error": "name and email are required"})
            continue

        try:
            participant = invite_participant(event_id, email, name)
            imported.append(
                {
                    "id": str(participant.id),
                    "name": participant.name,
                    "email": participant.email,
                }
            )
        except CTFValidationError as e:
            logger.warning("CTF participant import row %s failed: %s", idx, safe_log_value(str(e)))
            errors.append({"index": idx, "email": email, "error": "Could not import participant."})

    return JsonResponse(
        {
            "imported": len(imported),
            "participants": imported,
            "errors": errors,
        }
    )


def _participant_detail_payload(participant: CTFParticipant) -> dict[str, Any]:
    """Render the GET-participant JSON payload for `api_participant_detail`."""
    from ctf.models import CTFSubmission

    submissions = CTFSubmission.objects.filter(participant=participant)
    correct_submissions = submissions.filter(is_correct=True)
    return {
        "id": str(participant.id),
        "name": participant.name,
        "email": participant.email,
        "status": participant.status,
        "team_name": participant.team.name if participant.team else None,
        "registered_at": participant.registered_at.isoformat() if participant.registered_at else None,
        "invited_at": participant.invited_at.isoformat() if participant.invited_at else None,
        "last_active_at": participant.last_active_at.isoformat() if participant.last_active_at else None,
        "total_score": participant.total_score,
        "solved_count": correct_submissions.count(),
        "attempt_count": submissions.count(),
        "event_id": str(participant.event_id),
    }


def _handle_participant_delete(participant_id: UUID) -> JsonResponse:
    """Soft-delete a participant, returning a confirmation or a 404."""
    from ctf.exceptions import CTFNotFoundError
    from ctf.services import delete_participant

    try:
        delete_participant(participant_id)
    except CTFNotFoundError:
        return JsonResponse({"error": "Participant not found"}, status=404)
    return JsonResponse({"deleted": True, "id": str(participant_id)})


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "DELETE"])
def api_participant_detail(request: HttpRequest, participant_id: UUID) -> JsonResponse:
    """API: Get or remove participant.

    GET: Return participant details as JSON.
    DELETE: Soft-delete the participant.

    Args:
        participant_id: UUID of the participant.
    """
    participant, error = _resolve_owned_participant(request, participant_id)
    if error is not None:
        return error
    assert participant is not None

    if request.method == "GET":
        return JsonResponse(_participant_detail_payload(participant))
    return _handle_participant_delete(participant_id)


def _resend_invite_response(participant_id: UUID) -> JsonResponse:
    """Regenerate and resend a participant invite, returning success or a 400."""
    from ctf.exceptions import CTFStateError
    from ctf.services import resend_invite

    try:
        updated = resend_invite(participant_id)
    except CTFStateError as e:
        return _json_error(e, _INVALID_PARTICIPANT_REQUEST, 400)
    return JsonResponse(
        {
            "success": True,
            "id": str(updated.id),
            "invited": True,
        }
    )


@login_required
@ctf_organizer_required
@require_POST
def api_participant_resend_invite(request: HttpRequest, participant_id: UUID) -> JsonResponse:
    """API: Resend magic link email to a participant.

    Regenerates the invite token and sends a new email.
    Works for any participant regardless of registration status.

    Args:
        participant_id: UUID of the participant.
    """
    if not _check_invite_rate_limit(_get_user(request).pk):
        return JsonResponse({"error": "Too many invitations. Try again later."}, status=429)

    _participant, error = _resolve_owned_participant(request, participant_id)
    if error is not None:
        return error

    return _resend_invite_response(participant_id)
