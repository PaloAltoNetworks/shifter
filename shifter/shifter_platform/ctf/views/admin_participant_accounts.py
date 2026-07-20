"""Organizer workflows for creating isolated participant accounts."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from ctf.exceptions import CTFNotFoundError, CTFValidationError
from ctf.forms import CTFParticipantBatchForm
from ctf.services import get_event
from ctf.services.participant.accounts import create_participant_accounts
from ctf.views._access import ctf_organizer_required

if TYPE_CHECKING:
    from django.http import HttpRequest

_EVENT_NOT_FOUND_MSG = "Event not found"
_FORBIDDEN_EVENT_MSG = "Forbidden: You do not have access to this event"
_PARTICIPANT_LIST_ROUTE = "ctf:admin_participant_list"


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def admin_participant_batch(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Generate a bounded batch of isolated participant accounts."""
    from django.contrib import messages

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        raise Http404(_EVENT_NOT_FOUND_MSG) from None
    if event.created_by_id != request.user.pk:
        return HttpResponse(_FORBIDDEN_EVENT_MSG, status=403)
    form = CTFParticipantBatchForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            participants = create_participant_accounts(event_id, count=form.cleaned_data["count"])
        except CTFValidationError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, f"Generated {len(participants)} participant accounts.")
            return redirect(_PARTICIPANT_LIST_ROUTE, event_id=event_id)
    return render(request, "ctf/admin/participant_batch.html", {"event": event, "form": form})
