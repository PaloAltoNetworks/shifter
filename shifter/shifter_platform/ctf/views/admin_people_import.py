"""Legacy participant CSV import views, split from admin_people (python:S104).

Behavior unchanged; the view keeps its historical name and route.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from ctf.views._access import ctf_organizer_required
from ctf.views.admin_people import _EVENT_NOT_FOUND_MSG, _FORBIDDEN_EVENT_MSG, _PARTICIPANT_LIST_ROUTE
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from uuid import UUID

    from django.http import HttpRequest

    from ctf.exceptions import CTFValidationError

logger = logging.getLogger(__name__)


def _participant_import_error_messages(exc: CTFValidationError) -> list[str]:
    """Map a CSV participant-import validation error to display messages.

    Preserves the original precedence (existing > duplicates > generic), kept
    out of ``admin_participant_import`` to hold its cognitive complexity below
    the SonarCloud threshold (python:S3776).
    """
    details = exc.details
    errors = details.get("errors") or details.get("existing") or [str(exc)]
    if details.get("duplicates"):
        errors = [f"Duplicate emails: {', '.join(details['duplicates'])}"]
    if details.get("existing"):
        errors = [f"Already exists: {', '.join(details['existing'])}"]
    return errors


def _run_participant_import(request: HttpRequest, event_id: UUID) -> tuple[list[str] | None, int, HttpResponse | None]:
    """Run one CSV import POST; return (form errors, imported count, redirect).

    A redirect response means the import took (fully or partially) and row
    skips were flashed as warnings; errors mean the form re-renders.
    """
    from django.contrib import messages

    from ctf.exceptions import CTFValidationError
    from ctf.services import bulk_import_participants

    csv_file = request.FILES["csv_file"]
    try:
        csv_content = csv_file.read().decode("utf-8")  # type: ignore[union-attr]
        result = bulk_import_participants(event_id, csv_content)
    except CTFValidationError as e:
        return _participant_import_error_messages(e), 0, None
    imported_count = len(result["created"])
    if imported_count == 0 and result["errors"]:
        # Nothing importable: stay on the form and show every row error.
        return result["errors"], 0, None
    logger.info(
        "User %s imported %d participants to event %s",
        getattr(request.user, "email", ""),
        imported_count,
        safe_log_value(event_id),
    )
    messages.success(request, f"Successfully imported {imported_count} participants.")
    for row_error in result["errors"]:
        messages.warning(request, f"Skipped: {row_error}")
    return None, imported_count, redirect(_PARTICIPANT_LIST_ROUTE, event_id=event_id)


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def admin_participant_import(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Import participants from CSV.

    GET: Show import form.
    POST: Process CSV file and create participants.

    Args:
        event_id: UUID of the event.
    """
    from django.http import Http404

    from ctf.exceptions import CTFNotFoundError
    from ctf.forms import CTFParticipantImportForm
    from ctf.services import get_event

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        raise Http404(_EVENT_NOT_FOUND_MSG) from None

    # Check permission
    if event.created_by_id != request.user.pk:
        return HttpResponse(_FORBIDDEN_EVENT_MSG, status=403)

    errors = None
    imported_count = 0

    if request.method == "POST":
        form = CTFParticipantImportForm(request.POST, request.FILES)
        if form.is_valid():
            errors, imported_count, response = _run_participant_import(request, event_id)
            if response is not None:
                return response
    else:
        form = CTFParticipantImportForm()

    context = {
        "event": event,
        "form": form,
        "errors": errors,
        "imported_count": imported_count,
    }

    return render(request, "ctf/admin/participant_import.html", context)
