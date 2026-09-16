"""Organizer HTML endpoint for one-time participant credential issuance."""

from __future__ import annotations

from typing import TYPE_CHECKING, NoReturn, cast
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods

from ctf.views._access import ctf_organizer_required

if TYPE_CHECKING:
    from django.contrib.auth.models import User
    from django.http import HttpRequest

    from ctf.models import CTFParticipant
    from ctf.services import ParticipantPasswordIssuance

_FORBIDDEN_EVENT_MSG = "Forbidden: You do not have access to this event"
_PARTICIPANT_NOT_FOUND_MSG = "Participant not found"


class _ParticipantPasswordRejection(Exception):
    """Carry an intentional HTTP response out of credential validation."""

    def __init__(self, response: HttpResponse) -> None:
        super().__init__(response.reason_phrase)
        self.response = response


def _reject_participant_password(message: str, *, status: int, retry_after: str | None = None) -> NoReturn:
    """Stop password issuance with a deliberate, optionally retryable response."""
    response = HttpResponse(message, status=status)
    if retry_after is not None:
        response["Retry-After"] = retry_after
    raise _ParticipantPasswordRejection(response)


def _participant_password_target(request: HttpRequest, participant_id: UUID) -> tuple[CTFParticipant, User]:
    """Resolve an organizer-authorized participant credential target."""
    from django.http import Http404

    from ctf.exceptions import CTFNotFoundError
    from ctf.services import get_participant
    from ctf.services.event import actor_has_event_capability

    try:
        participant = get_participant(participant_id)
    except CTFNotFoundError:
        raise Http404(_PARTICIPANT_NOT_FOUND_MSG) from None
    if not actor_has_event_capability(request.user, participant.event, "participants"):
        _reject_participant_password(_FORBIDDEN_EVENT_MSG, status=403)
    actor = cast("User", request.user)
    if actor.pk is None:
        _reject_participant_password(_FORBIDDEN_EVENT_MSG, status=403)
    return participant, actor


def _enforce_participant_password_rate_limit(actor: User) -> None:
    """Apply the fail-closed credential-delivery rate limit."""
    from ctf.views._access import _check_credential_delivery_rate_limit

    try:
        allowed = _check_credential_delivery_rate_limit(actor.pk)
    except Exception:
        _reject_participant_password("Credential service is temporarily unavailable.", status=503)
    if not allowed:
        _reject_participant_password(
            "Too many credential operations. Try again later.",
            status=429,
            retry_after="3600",
        )


@sensitive_variables("password")
def _participant_password_input(request: HttpRequest) -> tuple[str, str | None]:
    """Parse and cross-check the organizer's password choice."""
    kind = request.POST.get("kind", "")
    password = request.POST.get("password") if kind == "set" else None
    if kind == "set" and password != request.POST.get("password_confirm"):
        _reject_participant_password("Passwords do not match.", status=400)
    return kind, password


@sensitive_variables("password")
def _issue_participant_password(
    request: HttpRequest,
    participant_id: UUID,
) -> tuple[CTFParticipant, ParticipantPasswordIssuance]:
    """Validate the request and execute one audited password issuance."""
    from ctf.exceptions import CTFValidationError
    from ctf.services import reset_participant_password
    from shared.audit import RequestAudit, get_client_ip, get_request_id

    participant, actor = _participant_password_target(request, participant_id)
    _enforce_participant_password_rate_limit(actor)
    kind, password = _participant_password_input(request)
    try:
        issuance = reset_participant_password(
            participant_id,
            actor=actor,
            kind=kind,
            password=password,
            request_audit=RequestAudit(
                source_ip=get_client_ip(request),
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:512],
                request_id=get_request_id(request),
            ),
        )
    except CTFValidationError:
        _reject_participant_password("Invalid participant password request.", status=400)
    return participant, issuance


@login_required
@ctf_organizer_required
@never_cache
@sensitive_post_parameters("password", "password_confirm")
@require_http_methods(["POST"])
def admin_participant_password(request: HttpRequest, participant_id: UUID) -> HttpResponse:
    """Issue one participant password and render it only in this response."""
    try:
        participant, issuance = _issue_participant_password(request, participant_id)
    except _ParticipantPasswordRejection as exc:
        return exc.response

    response = render(
        request,
        "ctf/admin/participant_password_result.html",
        {
            "participant": participant,
            "event": participant.event,
            "issuance": issuance,
        },
    )
    response["Cache-Control"] = "private, no-store"
    response["Pragma"] = "no-cache"
    response["Vary"] = "Cookie"
    return response
