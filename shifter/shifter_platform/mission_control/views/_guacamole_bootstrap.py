"""Guacamole bootstrap polling views."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_GET

from mission_control.guacamole_bootstrap import consume_ready_url
from mission_control.models import GuacamoleBootstrapRequest
from shared.errors import classify_user_message

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


def _bootstrap_urls(
    request_id: UUID,
    *,
    status_url_name: str = "v1:mission_control:guacamole-bootstrap-status",
    open_url_name: str = "v1:mission_control:guacamole-bootstrap-open",
) -> tuple[str, str]:
    """Return the polling URL and compatibility opener URL for a bootstrap."""
    kwargs = {"request_id": request_id}
    status_url = reverse(status_url_name, kwargs=kwargs)
    open_url = reverse(open_url_name, kwargs=kwargs)
    return status_url, open_url


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
        _clear_parked_url(bootstrap)
        payload["status"] = bootstrap.status
        payload["error"] = bootstrap.error_message or "Guacamole session request expired"
        status_code = 410
    elif bootstrap.status == GuacamoleBootstrapRequest.Status.SUCCEEDED:
        url = consume_ready_url(request_id=bootstrap.id, user_id=bootstrap.user_id)
        if url:
            # Single-use delivery: the URL is returned exactly once and the
            # token material is cleared from the row inside consume_ready_url.
            payload["url"] = url
        else:
            # A repeated poll after delivery must not replay the token URL.
            payload["error"] = "Guacamole session link is no longer available"
            status_code = 410
    elif bootstrap.status == GuacamoleBootstrapRequest.Status.FAILED:
        payload["error"] = classify_user_message(
            bootstrap.error_message,
            default="Guacamole session bootstrap failed",
        )
        status_code = bootstrap.error_status_code
    else:
        retry_after = True

    response = JsonResponse(payload, status=status_code)
    if retry_after:
        response["Retry-After"] = "1"
    return response


def _clear_parked_url(bootstrap: GuacamoleBootstrapRequest) -> None:
    """Clear a token URL still parked on an expired row before returning 410.

    A ``succeeded`` row that expired before any poll keeps ``result_url`` until
    pruning; the expired-poll response never delivers it, so clear it now to
    shrink the at-rest window rather than wait for the prune job.
    """
    if bootstrap.result_url:
        bootstrap.result_url = ""
        bootstrap.save(update_fields=("result_url", "updated_at"))


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
