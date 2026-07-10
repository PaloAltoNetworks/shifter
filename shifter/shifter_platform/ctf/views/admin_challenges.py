"""Organizer/admin challenge-management HTML views."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from django.http import HttpRequest

    from ctf.models import (
        CTFChallenge,
        CTFEvent,
    )

from ctf.views._access import (
    _get_user,
    ctf_organizer_required,
)

logger = logging.getLogger(__name__)

_ADMIN_CHALLENGE_DETAIL_URL = "ctf:admin_challenge_detail"
_FORBIDDEN_EVENT_MSG = "Forbidden: You do not have access to this event"

_FORBIDDEN_CHALLENGE_ACCESS_MSG = "Forbidden: You do not have access to this challenge"
_CHALLENGE_FORM_TEMPLATE = "ctf/admin/challenge_form.html"


@login_required
@ctf_organizer_required
def admin_challenge_list(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Challenge list for an event.

    Shows all challenges for the event with category grouping.

    Args:
        event_id: UUID of the event.
    """
    from django.http import Http404

    from ctf.exceptions import CTFNotFoundError
    from ctf.services import get_event, list_challenges_for_event

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        raise Http404("Event not found") from None

    # Check permission
    if event.created_by_id != request.user.pk:
        return HttpResponse(_FORBIDDEN_EVENT_MSG, status=403)

    challenges = list_challenges_for_event(event_id, actor_id=request.user.pk)

    # Group challenges by category
    from collections import defaultdict

    challenges_by_category = defaultdict(list)
    for challenge in challenges:
        challenges_by_category[challenge.category].append(challenge)

    # Calculate stats
    total_points = sum(c.points for c in challenges)

    context = {
        "event": event,
        "challenges": challenges,
        "challenges_by_category": dict(challenges_by_category),
        "total_points": total_points,
    }

    return render(request, "ctf/admin/challenge_list.html", context)


def _resolve_modifiable_event_for_challenge(
    request: HttpRequest, event_id: UUID
) -> tuple[CTFEvent | None, HttpResponse | None]:
    """Resolve the event and enforce ownership + content-modifiable; return (event, error_response)."""
    from django.http import Http404
    from django.shortcuts import redirect

    from ctf.exceptions import CTFNotFoundError
    from ctf.services import get_event

    try:
        event = get_event(event_id)
    except CTFNotFoundError:
        raise Http404("Event not found") from None

    if event.created_by_id != request.user.pk:
        return None, HttpResponse(_FORBIDDEN_EVENT_MSG, status=403)

    if not event.is_content_modifiable:
        logger.warning(
            "User %s attempted to add challenge to non-modifiable event %s",
            request.user.email,
            event.pk,
        )
        return None, redirect("ctf:admin_challenge_list", event_id=event.pk)

    return event, None


def _handle_challenge_create_post(request: HttpRequest, event: CTFEvent) -> HttpResponse:
    """Validate the create form and create the challenge, re-rendering the form on error."""
    from ctf.forms import CTFChallengeForm

    user = _get_user(request)
    form = CTFChallengeForm(request.POST, event=event)
    if form.is_valid():
        from ctf.exceptions import CTFPermissionError, CTFStateError, CTFValidationError
        from ctf.services.challenge import create_challenge

        try:
            challenge = create_challenge(
                event_id=event.pk,
                challenge_data=form.to_service_data(),
                actor_id=user.pk,
            )
        except CTFPermissionError:
            return HttpResponse(_FORBIDDEN_EVENT_MSG, status=403)
        except (CTFStateError, CTFValidationError) as e:
            form.add_error(None, str(e))
        else:
            logger.info(
                "User %s created challenge %s: %s for event %s",
                user.email,
                challenge.pk,
                challenge.name,
                event.pk,
            )
            return redirect(_ADMIN_CHALLENGE_DETAIL_URL, challenge_id=challenge.pk)

    context = {"form": form, "event": event, "is_edit": False}
    return render(request, _CHALLENGE_FORM_TEMPLATE, context)


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def admin_challenge_create(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Create new challenge.

    GET: Show creation form.
    POST: Process creation.

    Args:
        event_id: UUID of the event.
    """
    from ctf.forms import CTFChallengeForm

    event, error = _resolve_modifiable_event_for_challenge(request, event_id)
    if error is not None:
        return error
    # error is None implies the event resolved and is modifiable.
    assert event is not None

    if request.method == "POST":
        return _handle_challenge_create_post(request, event)

    form = CTFChallengeForm(event=event)
    context = {"form": form, "event": event, "is_edit": False}
    return render(request, _CHALLENGE_FORM_TEMPLATE, context)


@login_required
@ctf_organizer_required
def admin_challenge_detail(request: HttpRequest, challenge_id: UUID) -> HttpResponse:
    """Challenge detail view.

    Shows challenge information, solve statistics, and recent submissions.

    Args:
        challenge_id: UUID of the challenge.
    """
    from django.http import Http404

    from ctf.exceptions import CTFNotFoundError
    from ctf.services import get_challenge

    try:
        challenge = get_challenge(challenge_id)
    except CTFNotFoundError:
        raise Http404("Challenge not found") from None

    # Check permission
    if challenge.event.created_by_id != request.user.pk:
        return HttpResponse(_FORBIDDEN_CHALLENGE_ACCESS_MSG, status=403)

    # Get submission stats
    from ctf.models import CTFChallenge, CTFSubmission

    submissions = CTFSubmission.objects.filter(challenge=challenge).order_by("-submitted_at")
    total_submissions = submissions.count()
    correct_submissions = submissions.filter(is_correct=True).count()
    recent_submissions = submissions[:10]

    # Get first blood if any
    first_blood = challenge.first_blood

    # Get flags for this challenge
    flags = challenge.flags.all()

    # Get files for this challenge
    from ctf.services.attachment import get_challenge_files

    challenge_files = get_challenge_files(challenge_id)

    # Get prerequisites
    from ctf.services.challenge import get_prerequisites

    prerequisites = get_prerequisites(challenge_id)

    # Get other challenges in this event (for prerequisite selector)
    other_challenges = (
        CTFChallenge.objects.filter(
            event=challenge.event,
        )
        .exclude(pk=challenge_id)
        .order_by("category", "name")
    )

    # Rating stats
    from ctf.services.submission import get_challenge_rating

    rating_data = get_challenge_rating(challenge_id)

    context = {
        "challenge": challenge,
        "event": challenge.event,
        "total_submissions": total_submissions,
        "correct_submissions": correct_submissions,
        "recent_submissions": recent_submissions,
        "first_blood": first_blood,
        "flags": flags,
        "challenge_files": challenge_files,
        "prerequisites": prerequisites,
        "other_challenges": other_challenges,
        "rating": rating_data,
    }

    return render(request, "ctf/admin/challenge_detail.html", context)


def _resolve_editable_challenge(
    request: HttpRequest, challenge_id: UUID
) -> tuple[CTFChallenge | None, HttpResponse | None]:
    """Resolve the challenge and enforce ownership + content-modifiable; return (challenge, error_response)."""
    from django.http import Http404
    from django.shortcuts import redirect

    from ctf.exceptions import CTFNotFoundError
    from ctf.services import get_challenge

    try:
        challenge = get_challenge(challenge_id)
    except CTFNotFoundError:
        raise Http404("Challenge not found") from None

    event = challenge.event
    if event.created_by_id != request.user.pk:
        return None, HttpResponse(_FORBIDDEN_CHALLENGE_ACCESS_MSG, status=403)

    if not event.is_content_modifiable:
        logger.warning(
            "User %s attempted to edit challenge %s in non-modifiable event %s",
            request.user.email,
            challenge.pk,
            event.pk,
        )
        return None, redirect(_ADMIN_CHALLENGE_DETAIL_URL, challenge_id=challenge.pk)

    return challenge, None


def _handle_challenge_edit_post(request: HttpRequest, challenge: CTFChallenge, event: CTFEvent) -> HttpResponse:
    """Validate the edit form and update the challenge, re-rendering the form on error."""
    from ctf.forms import CTFChallengeForm

    user = _get_user(request)
    form = CTFChallengeForm(request.POST, instance=challenge, event=event)
    if form.is_valid():
        from ctf.exceptions import CTFPermissionError, CTFStateError, CTFValidationError
        from ctf.services.challenge import update_challenge

        try:
            update_challenge(
                challenge_id=challenge.pk,
                challenge_data=form.to_service_data(),
                actor_id=user.pk,
            )
        except CTFPermissionError:
            return HttpResponse(_FORBIDDEN_CHALLENGE_ACCESS_MSG, status=403)
        except (CTFStateError, CTFValidationError) as e:
            form.add_error(None, str(e))
        else:
            logger.info(
                "User %s updated challenge %s: %s",
                user.email,
                challenge.pk,
                challenge.name,
            )
            return redirect(_ADMIN_CHALLENGE_DETAIL_URL, challenge_id=challenge.pk)

    context = {"form": form, "event": event, "challenge": challenge, "is_edit": True}
    return render(request, _CHALLENGE_FORM_TEMPLATE, context)


@login_required
@ctf_organizer_required
@require_http_methods(["GET", "POST"])
def admin_challenge_edit(request: HttpRequest, challenge_id: UUID) -> HttpResponse:
    """Edit challenge.

    GET: Show edit form.
    POST: Process update.

    Args:
        challenge_id: UUID of the challenge.
    """
    from ctf.forms import CTFChallengeForm

    challenge, error = _resolve_editable_challenge(request, challenge_id)
    if error is not None:
        return error
    # error is None implies the challenge resolved and its event is modifiable.
    assert challenge is not None
    event = challenge.event

    if request.method == "POST":
        return _handle_challenge_edit_post(request, challenge, event)

    form = CTFChallengeForm(instance=challenge, event=event)
    context = {"form": form, "event": event, "challenge": challenge, "is_edit": True}
    return render(request, _CHALLENGE_FORM_TEMPLATE, context)


def _admin_upload_challenge_file(request: HttpRequest, challenge_id: UUID) -> HttpResponse:
    """Add the uploaded file (if any) then redirect to the detail page; 403 on permission error."""
    if not request.FILES.get("file"):
        return redirect(_ADMIN_CHALLENGE_DETAIL_URL, challenge_id=challenge_id)

    from django.core.files.uploadedfile import UploadedFile

    from ctf.exceptions import CTFNotFoundError, CTFPermissionError, CTFStateError, CTFValidationError
    from ctf.services.attachment import add_challenge_file

    uploaded_file = cast(UploadedFile, request.FILES["file"])
    display_name = request.POST.get("display_name", "")

    try:
        add_challenge_file(
            challenge_id=challenge_id,
            file_obj=uploaded_file,
            filename=uploaded_file.name or "unnamed",
            display_name=display_name,
            content_type=uploaded_file.content_type or "application/octet-stream",
            actor_id=_get_user(request).pk,
        )
    except CTFPermissionError:
        return HttpResponse("Forbidden", status=403)
    except (CTFNotFoundError, CTFStateError, CTFValidationError) as e:
        logger.warning("File upload failed for challenge %s: %s", safe_log_value(challenge_id), e)

    return redirect(_ADMIN_CHALLENGE_DETAIL_URL, challenge_id=challenge_id)


@login_required
@ctf_organizer_required
@require_POST
def admin_challenge_file_upload(request: HttpRequest, challenge_id: UUID) -> HttpResponse:
    """Upload a challenge file from the admin detail page.

    Redirects back to the challenge detail page.
    """
    from ctf.exceptions import CTFNotFoundError
    from ctf.services.challenge import get_challenge

    try:
        challenge = get_challenge(challenge_id)
    except CTFNotFoundError:
        return redirect(_ADMIN_CHALLENGE_DETAIL_URL, challenge_id=challenge_id)

    if challenge.event.created_by_id != request.user.pk:
        return HttpResponse("Forbidden", status=403)

    return _admin_upload_challenge_file(request, challenge_id)
