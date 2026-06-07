"""Guacamole bootstrap polling views."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_GET

from mission_control.guacamole_bootstrap import BootstrapQueueFull, enqueue_guacamole_bootstrap
from mission_control.models import GuacamoleBootstrapRequest
from shared.log_sanitize import safe_log_value

from ._common import _get_user

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


class _BootstrapViewError(Exception):
    """Internal exception carrying a pre-built JsonResponse for early return."""

    def __init__(self, response: JsonResponse) -> None:
        super().__init__()
        self.response = response


def _authenticated_user_id(user: User) -> int:
    """Return the authenticated user's integer id."""
    for attr in ("pk", "id"):
        value = getattr(user, attr, None)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    raise _BootstrapViewError(JsonResponse({"error": "Authenticated user id unavailable"}, status=500))


def _bootstrap_urls(request_id: UUID) -> tuple[str, str]:
    """Return the polling URL and compatibility opener URL for a bootstrap."""
    kwargs = {"request_id": request_id}
    status_url = reverse("mission_control:guacamole_bootstrap_status", kwargs=kwargs)
    open_url = reverse("mission_control:guacamole_bootstrap_open", kwargs=kwargs)
    return status_url, open_url


def guacamole_bootstrap_response(
    *,
    user: User,
    protocol: str,
    target_id: str,
    build_url: Callable[[], str],
) -> JsonResponse:
    """Enqueue Guacamole bootstrap work and return a pollable response."""
    try:
        bootstrap = enqueue_guacamole_bootstrap(
            user_id=_authenticated_user_id(user),
            protocol=protocol,
            target_id=target_id,
            build_url=build_url,
        )
    except _BootstrapViewError as err:
        return err.response
    except BootstrapQueueFull:
        logger.warning(
            "Guacamole bootstrap worker capacity exhausted: user=%s protocol=%s target_id=%s",
            safe_log_value(user.email),
            safe_log_value(protocol),
            safe_log_value(target_id),
        )
        response = JsonResponse({"error": "Guacamole session service is busy. Try again shortly."}, status=503)
        response["Retry-After"] = "1"
        return response

    status_url, open_url = _bootstrap_urls(bootstrap.id)
    response = JsonResponse(
        {
            "request_id": str(bootstrap.id),
            "status": bootstrap.status,
            "status_url": status_url,
            "url": open_url,
        },
        status=202,
    )
    response["Location"] = status_url
    response["Retry-After"] = "1"
    return response


@login_required
@require_GET
def guacamole_bootstrap_status(request: HttpRequest, request_id: UUID) -> JsonResponse:
    """Return the current status for an asynchronous Guacamole bootstrap."""
    user = _get_user(request)
    try:
        bootstrap = GuacamoleBootstrapRequest.objects.get(pk=request_id, user_id=_authenticated_user_id(user))
    except GuacamoleBootstrapRequest.DoesNotExist:
        return JsonResponse({"error": "Guacamole bootstrap request not found"}, status=404)
    except _BootstrapViewError as err:
        return err.response
    return _status_response(bootstrap)


@login_required
@require_GET
def guacamole_bootstrap_open(request: HttpRequest, request_id: UUID) -> HttpResponse:
    """Render a lightweight compatibility opener for legacy URL clients."""
    user = _get_user(request)
    try:
        GuacamoleBootstrapRequest.objects.only("id").get(pk=request_id, user_id=_authenticated_user_id(user))
    except GuacamoleBootstrapRequest.DoesNotExist:
        return HttpResponse("Guacamole session request not found.", status=404, content_type="text/plain")
    except _BootstrapViewError as err:
        return err.response

    status_url, _open_url = _bootstrap_urls(request_id)
    status_url_json = json.dumps(status_url)
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Opening session</title>
</head>
<body>
  <p id="status">Opening session...</p>
  <script>
    const statusUrl = {status_url_json};
    const statusEl = document.getElementById('status');
    let attempts = 0;
    async function poll() {{
      attempts += 1;
      const response = await fetch(statusUrl, {{ headers: {{ 'Accept': 'application/json' }} }});
      const data = await response.json().catch(() => ({{}}));
      if (!response.ok) {{
        statusEl.textContent = data.error || 'Failed to open session.';
        return;
      }}
      if (data.url) {{
        globalThis.location.replace(data.url);
        return;
      }}
      if (attempts >= 60) {{
        statusEl.textContent = 'Session request timed out.';
        return;
      }}
      setTimeout(poll, 1000);
    }}
    poll().catch(() => {{
      statusEl.textContent = 'Failed to open session.';
    }});
  </script>
</body>
</html>"""
    return HttpResponse(html)


def _status_response(bootstrap: GuacamoleBootstrapRequest) -> JsonResponse:
    """Build the JSON response for a bootstrap row."""
    payload: dict[str, str | int] = {
        "request_id": str(bootstrap.id),
        "status": bootstrap.status,
    }
    status_code = 200
    retry_after = False

    if bootstrap.duration_ms is not None:
        payload["duration_ms"] = bootstrap.duration_ms

    if bootstrap.is_expired:
        _mark_expired(bootstrap)
        payload["status"] = bootstrap.status
        payload["error"] = bootstrap.error_message or "Guacamole session request expired"
        status_code = 410
    elif bootstrap.status == GuacamoleBootstrapRequest.Status.SUCCEEDED:
        payload["url"] = bootstrap.result_url
    elif bootstrap.status == GuacamoleBootstrapRequest.Status.FAILED:
        payload["error"] = bootstrap.error_message or "Guacamole session bootstrap failed"
        status_code = bootstrap.error_status_code
    else:
        retry_after = True

    response = JsonResponse(payload, status=status_code)
    if retry_after:
        response["Retry-After"] = "1"
    return response


def _mark_expired(bootstrap: GuacamoleBootstrapRequest) -> None:
    """Persist expiry as a failed bootstrap when the work did not finish."""
    if bootstrap.status not in {
        GuacamoleBootstrapRequest.Status.PENDING,
        GuacamoleBootstrapRequest.Status.RUNNING,
    }:
        return
    bootstrap.status = GuacamoleBootstrapRequest.Status.FAILED
    bootstrap.error_message = "Guacamole session request expired"
    bootstrap.error_status_code = 410
    bootstrap.save(update_fields=("status", "error_message", "error_status_code", "updated_at"))
