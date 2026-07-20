"""Organizer/admin bracket-management views and bracket assignment API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

if TYPE_CHECKING:
    from django.http import HttpRequest


from ctf.views._access import (
    _json_error,
    _resolve_owned_participant,
    ctf_organizer_required,
)
from ctf.views._parsing import (
    _BodyParseError,
    _parse_body_object,
)

logger = logging.getLogger(__name__)

_BRACKET_NOT_FOUND = "Bracket not found"
_FORBIDDEN_EVENT_MSG = "Forbidden: You do not have access to this event"
_ADMIN_BRACKET_LIST_URL = "ctf:admin_bracket_list"


@login_required
@ctf_organizer_required
def admin_bracket_list(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """List brackets for an event.

    Args:
        event_id: UUID of the event.
    """
    from django.http import Http404

    from ctf.exceptions import CTFNotFoundError
    from ctf.services import get_event
    from ctf.services.bracket import list_brackets

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        raise Http404("Event not found") from None

    if event.created_by_id != request.user.pk:
        return HttpResponse(_FORBIDDEN_EVENT_MSG, status=403)

    brackets = list_brackets(event.id)

    return render(
        request,
        "ctf/admin/bracket_list.html",
        {"event": event, "brackets": brackets},
    )


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def admin_bracket_create(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Create a bracket for an event.

    Args:
        event_id: UUID of the event.
    """
    from django.contrib import messages
    from django.http import Http404

    from ctf.exceptions import CTFNotFoundError
    from ctf.forms import CTFBracketForm
    from ctf.services import get_event

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        raise Http404("Event not found") from None

    if event.created_by_id != request.user.pk:
        return HttpResponse(_FORBIDDEN_EVENT_MSG, status=403)

    if request.method == "POST":
        form = CTFBracketForm(request.POST, event=event)
        if form.is_valid():
            form.save()
            messages.success(request, f"Bracket '{form.cleaned_data['name']}' created.")
            return redirect(_ADMIN_BRACKET_LIST_URL, event_id=event_id)
    else:
        form = CTFBracketForm(event=event)

    return render(
        request,
        "ctf/admin/bracket_form.html",
        {"event": event, "form": form, "editing": False},
    )


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def admin_bracket_edit(request: HttpRequest, bracket_id: UUID) -> HttpResponse:
    """Edit a bracket.

    Args:
        bracket_id: UUID of the bracket.
    """
    from django.contrib import messages
    from django.http import Http404

    from ctf.forms import CTFBracketForm
    from ctf.models import CTFBracket

    try:
        bracket = CTFBracket.objects.select_related("event").get(pk=bracket_id)
    except CTFBracket.DoesNotExist:
        raise Http404(_BRACKET_NOT_FOUND) from None

    event = bracket.event
    if event.created_by_id != request.user.pk:
        return HttpResponse(_FORBIDDEN_EVENT_MSG, status=403)

    if request.method == "POST":
        form = CTFBracketForm(request.POST, instance=bracket, event=event)
        if form.is_valid():
            form.save()
            messages.success(request, f"Bracket '{bracket.name}' updated.")
            return redirect(_ADMIN_BRACKET_LIST_URL, event_id=event.id)
    else:
        form = CTFBracketForm(instance=bracket, event=event)

    return render(
        request,
        "ctf/admin/bracket_form.html",
        {"event": event, "form": form, "bracket": bracket, "editing": True},
    )


@login_required
@ctf_organizer_required
@require_http_methods(["POST"])
def admin_bracket_delete(request: HttpRequest, bracket_id: UUID) -> HttpResponse:
    """Delete a bracket.

    Args:
        bracket_id: UUID of the bracket.
    """
    from django.contrib import messages
    from django.http import Http404

    from ctf.models import CTFBracket
    from ctf.services.bracket import delete_bracket, get_bracket

    try:
        bracket = get_bracket(bracket_id)
    except CTFBracket.DoesNotExist:
        raise Http404(_BRACKET_NOT_FOUND) from None

    event = bracket.event
    if event.created_by_id != request.user.pk:
        return HttpResponse(_FORBIDDEN_EVENT_MSG, status=403)

    name = bracket.name
    delete_bracket(bracket_id)
    messages.success(request, f"Bracket '{name}' deleted.")
    return redirect(_ADMIN_BRACKET_LIST_URL, event_id=event.id)


def _set_participant_bracket(participant_id: UUID, bracket_id: object) -> JsonResponse:
    """Assign (bracket_id given) or remove (bracket_id None) a participant's bracket."""
    if bracket_id is None:
        from ctf.services.bracket import remove_participant_bracket

        remove_participant_bracket(participant_id)
        return JsonResponse({"status": "ok", "bracket": None})

    from uuid import UUID as _UUID

    from ctf.models import CTFBracket
    from ctf.services.bracket import assign_participant_bracket

    participant = None
    error: tuple[str, int] | None = None
    try:
        bracket_uuid = _UUID(str(bracket_id))
        participant = assign_participant_bracket(participant_id, bracket_uuid)
    except ValueError:
        error = ("Invalid bracket ID format", 400)
    except ValidationError:
        error = ("Bracket and participant must belong to the same event", 400)
    except CTFBracket.DoesNotExist:
        error = (_BRACKET_NOT_FOUND, 404)
    if error is not None:
        return JsonResponse({"error": error[0]}, status=error[1])

    assert participant is not None
    bracket = participant.bracket
    return JsonResponse(
        {
            "status": "ok",
            "bracket": {"id": str(bracket.id), "name": bracket.name} if bracket else None,
        }
    )


@login_required
@ctf_organizer_required
@require_http_methods(["POST"])
def api_assign_bracket(request: HttpRequest, participant_id: UUID) -> JsonResponse:
    """API: Assign or remove a participant's bracket.

    POST body: {"bracket_id": "<uuid>" | null}

    Args:
        participant_id: UUID of the participant.
    """
    _participant, error = _resolve_owned_participant(request, participant_id)
    if error is not None:
        return error

    try:
        body = _parse_body_object(request)
    except _BodyParseError as e:
        return _json_error(e, "Invalid bracket request.", 400)

    return _set_participant_bracket(participant_id, body.get("bracket_id"))
