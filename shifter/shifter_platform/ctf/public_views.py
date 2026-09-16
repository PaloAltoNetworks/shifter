"""Hardened public browser surface for explicitly published CTF events."""

from __future__ import annotations

import hashlib
import logging
from uuid import UUID

from django.core.cache import caches
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from ctf.forms import PublicRegistrationForm
from ctf.services.public_registration import (
    PublicEventProjection,
    PublicEventUnavailable,
    PublicRegistrationClosed,
    PublicRegistrationQueueFull,
    resolve_public_event,
    submit_public_registration_request,
)
from shared.audit import get_client_ip
from shared.log_sanitize import safe_log_value
from shared.rate_limit import consume_fixed_window

PUBLIC_RATE_WINDOW_SECONDS = 60 * 60
PUBLIC_SOURCE_LIMIT = 12
PUBLIC_EVENT_LIMIT = 1_000
PUBLIC_FLEET_LIMIT = 5_000
PUBLIC_MAX_BODY_BYTES = 4_096
_NOT_FOUND_MESSAGE = "Not found."
_TEMPORARILY_UNAVAILABLE_MESSAGE = "Registration is temporarily unavailable."

logger = logging.getLogger(__name__)


def _private_response(response: HttpResponse) -> HttpResponse:
    """Apply the most restrictive browser metadata supported by this surface."""
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


def _render_public(
    request: HttpRequest,
    projection: PublicEventProjection,
    *,
    form: PublicRegistrationForm | None = None,
    submitted: bool = False,
    status: int = 200,
) -> HttpResponse:
    """Render the public template with private-response browser metadata."""
    return _private_response(
        render(
            request,
            "ctf/public/registration.html",
            {"event": projection, "form": form or PublicRegistrationForm(), "submitted": submitted},
            status=status,
        )
    )


def _fixed_response(message: str, *, status: int, retry_after: int | None = None) -> HttpResponse:
    """Return a fixed-size plain-text error without disclosing event state."""
    response = _private_response(HttpResponse(message, status=status, content_type="text/plain; charset=utf-8"))
    if retry_after is not None:
        response["Retry-After"] = str(retry_after)
    return response


def _content_length_allowed(request: HttpRequest) -> bool:
    """Reject malformed or oversized request bodies before form parsing."""
    raw = request.META.get("CONTENT_LENGTH", "0")
    try:
        return int(raw or 0) <= PUBLIC_MAX_BODY_BYTES
    except (TypeError, ValueError):
        return False


def _source_digest(request: HttpRequest) -> str:
    """Hash the client address used by the source-scoped rate-limit key."""
    source = str(get_client_ip(request) or "unknown")
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:24]


def _consume_public_budget(request: HttpRequest, event_id: UUID) -> bool:
    """Charge every public-intake limiter and report whether all permit it."""
    cache = caches["launch_rate_limit"]
    counters = (
        (f"ctf-public-registration:source:{event_id}:{_source_digest(request)}", PUBLIC_SOURCE_LIMIT),
        (f"ctf-public-registration:event:{event_id}", PUBLIC_EVENT_LIMIT),
        ("ctf-public-registration:fleet", PUBLIC_FLEET_LIMIT),
    )
    usage = [(consume_fixed_window(cache, key, PUBLIC_RATE_WINDOW_SECONDS), limit) for key, limit in counters]
    return all(count <= limit for count, limit in usage)


def _admission_rejection(request: HttpRequest, event_id: UUID) -> HttpResponse | None:
    """Return a bounded intake rejection, or ``None`` when parsing may proceed."""
    response = None
    try:
        admitted = _consume_public_budget(request, event_id)
    except Exception:
        logger.exception("Public CTF registration limiter unavailable for event %s", safe_log_value(event_id))
        response = _fixed_response(_TEMPORARILY_UNAVAILABLE_MESSAGE, status=503)
    else:
        if not admitted:
            response = _fixed_response(
                "Too many registration attempts. Try again later.",
                status=429,
                retry_after=PUBLIC_RATE_WINDOW_SECONDS,
            )
        elif not _content_length_allowed(request):
            response = _fixed_response("The registration request is invalid.", status=400)
    return response


def _closed_registration_response(
    request: HttpRequest,
    event_id: UUID,
    form: PublicRegistrationForm,
) -> HttpResponse:
    """Render the closed state unless the event became undiscoverable."""
    try:
        projection = resolve_public_event(event_id)
    except PublicEventUnavailable:
        response = _fixed_response(_NOT_FOUND_MESSAGE, status=404)
    else:
        response = _render_public(request, projection, form=form, status=409)
    return response


def _submit_valid_registration(
    request: HttpRequest,
    event_id: UUID,
    projection: PublicEventProjection,
    form: PublicRegistrationForm,
) -> HttpResponse:
    """Persist one valid form and map service outcomes to public responses."""
    try:
        submit_public_registration_request(
            event_id,
            name=form.cleaned_data["name"],
            email=form.cleaned_data["email"],
        )
    except PublicRegistrationClosed:
        response = _closed_registration_response(request, event_id, form)
    except PublicEventUnavailable:
        response = _fixed_response(_NOT_FOUND_MESSAGE, status=404)
    except PublicRegistrationQueueFull:
        logger.warning("Public CTF registration queue full for event %s", safe_log_value(event_id))
        response = _fixed_response(_TEMPORARILY_UNAVAILABLE_MESSAGE, status=503)
    except (ValidationError, IntegrityError):
        logger.exception("Public CTF registration persistence failed for event %s", safe_log_value(event_id))
        response = _fixed_response(_TEMPORARILY_UNAVAILABLE_MESSAGE, status=503)
    else:
        response = _render_public(request, projection, submitted=True)
    return response


def _handle_public_registration_post(
    request: HttpRequest,
    event_id: UUID,
    projection: PublicEventProjection,
) -> HttpResponse:
    """Validate and submit a public registration POST."""
    response = _admission_rejection(request, event_id)
    if response is None:
        form = PublicRegistrationForm(request.POST)
        if form.is_valid():
            response = _submit_valid_registration(request, event_id, projection, form)
        else:
            response = _render_public(request, projection, form=form, status=400)
    return response


@never_cache
@ensure_csrf_cookie
@require_http_methods(["GET", "POST"])
def public_event_registration(request: HttpRequest, event_id: UUID) -> HttpResponse:
    """Render an allowlisted event projection or accept one pending request."""
    try:
        projection = resolve_public_event(event_id)
    except PublicEventUnavailable:
        response = _fixed_response(_NOT_FOUND_MESSAGE, status=404)
    else:
        response = (
            _render_public(request, projection)
            if request.method == "GET"
            else _handle_public_registration_post(request, event_id, projection)
        )
    return response
