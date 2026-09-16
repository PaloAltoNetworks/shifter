"""Public browser handoff for signed workspace invitations (#1942)."""

import hashlib
import json

from django.core.cache import cache
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST, require_safe

from shared.audit import get_client_ip
from shared.rate_limit import consume_fixed_window
from shared.workspace_invitation_handoff import INVITATION_OUTCOME_SESSION_KEY, STAGED_INVITATION_SESSION_KEY
from workspaces import services

_STAGING_LIMIT = 12
_STAGING_WINDOW_SECONDS = 60 * 60


def _private_response[ResponseT: HttpResponse](response: ResponseT) -> ResponseT:
    """Apply credential-safe cache and referrer controls."""
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


@never_cache
@ensure_csrf_cookie
@require_safe
def invitation_accept(request: HttpRequest) -> HttpResponse:
    """Render the credential-free fragment exchange landing or bounded result."""
    outcome = request.session.pop(INVITATION_OUTCOME_SESSION_KEY, None)
    return _private_response(render(request, "workspaces/invitations/accept.html", {"outcome": outcome}))


def _staging_rate_key(request: HttpRequest) -> str:
    """Return a PII-free fixed-window key for the request source."""
    source = get_client_ip(request) or "unknown"
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:24]
    return f"workspace-invitation-stage:{digest}"


@never_cache
@require_POST
def invitation_stage(request: HttpRequest) -> JsonResponse:
    """Exchange a fragment credential for a non-secret session reference."""
    response: JsonResponse
    try:
        if consume_fixed_window(cache, _staging_rate_key(request), _STAGING_WINDOW_SECONDS) > _STAGING_LIMIT:
            response = JsonResponse({"error": "invitation_throttled"}, status=429)
            response["Retry-After"] = str(_STAGING_WINDOW_SECONDS)
            return _private_response(response)
        payload = json.loads(request.body.decode("utf-8"))
        token = payload.get("token") if isinstance(payload, dict) else None
        claim = services.stage_workspace_invitation_token(token)
    except (UnicodeDecodeError, json.JSONDecodeError, services.WorkspaceInvitationError):
        response = JsonResponse({"error": "invitation_invalid"}, status=400)
    except Exception:
        response = JsonResponse({"error": "invitation_unavailable"}, status=503)
    else:
        request.session[STAGED_INVITATION_SESSION_KEY] = {
            "invitation_uuid": str(claim.invitation_uuid),
            "generation": str(claim.generation),
        }
        response = JsonResponse({"redirect_url": reverse("platform_login")})
    return _private_response(response)
