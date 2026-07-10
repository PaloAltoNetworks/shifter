"""Guacamole bootstrap DRF views for Mission Control."""

from __future__ import annotations

from collections.abc import Callable
from logging import Logger
from typing import TYPE_CHECKING
from uuid import UUID

from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from rest_framework.request import Request
from rest_framework.response import Response

from mission_control.api._base import (
    MissionControlReadAPIView,
    _guacamole_bootstrap_url_names,
    _guacamole_read_permission,
    _validated,
)
from mission_control.api.permissions import HasMissionControlActor
from mission_control.api.serializers import GuacamoleInstanceSerializer
from mission_control.guacamole_bootstrap import consume_ready_url
from mission_control.models import GuacamoleBootstrapRequest
from mission_control.views._guacamole import (
    _resolve_and_build_ngfw_ssh_url,
    _resolve_and_build_range_ssh_url,
    _resolve_and_build_rdp_url,
    _wrap_bootstrap_error,
)
from mission_control.views._guacamole_bootstrap import _authenticated_user_id, _BootstrapViewError, _mark_expired
from mission_control.views._guacamole_bootstrap import guacamole_bootstrap_response as _guacamole_bootstrap_response
from shared.api.permissions import IsAuthenticatedSessionOrApiToken
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from django.contrib.auth.models import User

GuacamoleSettings = tuple[str, str, str | None]


def _get_guac_settings(service_name: str) -> GuacamoleSettings:
    """Resolve Guacamole settings through the public compatibility module."""
    from mission_control.api import views as api_views

    return api_views._get_guac_settings(service_name)


class GuacamoleRDPURLView(MissionControlReadAPIView):
    """Queue Guacamole URL bootstrap for range RDP access."""

    permission_classes = [IsAuthenticatedSessionOrApiToken, HasMissionControlActor, _guacamole_read_permission()]

    def post(self, request: Request) -> JsonResponse | Response:
        """Queue an RDP bootstrap request for a range instance."""
        data, error = _validated(self, GuacamoleInstanceSerializer, request.data)
        if error is not None:
            return error
        assert data is not None
        user = self.actor_user()
        try:
            guac_settings = _get_guac_settings("RDP")
        except Exception as exc:
            if hasattr(exc, "response"):
                return exc.response
            raise
        return _range_bootstrap_response(
            request=request,
            user=user,
            protocol=GuacamoleBootstrapRequest.Protocol.RDP,
            target_id=data["instance_uuid"],
            build_url=lambda: _wrap_bootstrap_error(
                "RDP",
                lambda: _resolve_and_build_rdp_url(
                    user=user,
                    instance_uuid=data["instance_uuid"],
                    guac_settings=guac_settings,
                ),
            ),
        )


class GuacamoleRangeSSHURLView(MissionControlReadAPIView):
    """Queue Guacamole URL bootstrap for range SSH access."""

    permission_classes = [IsAuthenticatedSessionOrApiToken, HasMissionControlActor, _guacamole_read_permission()]

    def post(self, request: Request) -> JsonResponse | Response:
        """Queue an SSH bootstrap request for a range instance."""
        data, error = _validated(self, GuacamoleInstanceSerializer, request.data)
        if error is not None:
            return error
        assert data is not None
        user = self.actor_user()
        try:
            guac_settings = _get_guac_settings("SSH")
        except Exception as exc:
            if hasattr(exc, "response"):
                return exc.response
            raise
        return _range_bootstrap_response(
            request=request,
            user=user,
            protocol=GuacamoleBootstrapRequest.Protocol.RANGE_SSH,
            target_id=data["instance_uuid"],
            build_url=lambda: _wrap_bootstrap_error(
                "SSH",
                lambda: _resolve_and_build_range_ssh_url(
                    user=user,
                    instance_uuid=data["instance_uuid"],
                    guac_settings=guac_settings,
                ),
            ),
        )


class GuacamoleNGFWSSHURLView(MissionControlReadAPIView):
    """Queue Guacamole URL bootstrap for NGFW SSH access."""

    permission_classes = [IsAuthenticatedSessionOrApiToken, HasMissionControlActor, _guacamole_read_permission()]

    def post(self, request: Request, app_id: str) -> JsonResponse | Response:
        """Queue an SSH bootstrap request for an NGFW instance."""
        user = self.actor_user()
        try:
            guac_settings = _get_guac_settings("SSH")
        except Exception as exc:
            if hasattr(exc, "response"):
                return exc.response
            raise
        _range_logger().info(
            "Guacamole SSH bootstrap queued for NGFW: user=%s ngfw_uuid=%s",
            safe_log_value(user.email),
            safe_log_value(app_id),
        )
        return _range_bootstrap_response(
            request=request,
            user=user,
            protocol=GuacamoleBootstrapRequest.Protocol.NGFW_SSH,
            target_id=str(app_id),
            build_url=lambda: _wrap_bootstrap_error(
                "SSH",
                lambda: _resolve_and_build_ngfw_ssh_url(user=user, app_id=app_id, guac_settings=guac_settings),
            ),
        )


class GuacamoleBootstrapStatusView(MissionControlReadAPIView):
    """Return Guacamole bootstrap status."""

    permission_classes = [IsAuthenticatedSessionOrApiToken, HasMissionControlActor, _guacamole_read_permission()]

    def get(self, request: Request, request_id: UUID) -> JsonResponse:
        """Return current status for a queued Guacamole bootstrap request."""
        user = self.actor_user()
        try:
            bootstrap = GuacamoleBootstrapRequest.objects.get(pk=request_id, user_id=_authenticated_user_id(user))
        except GuacamoleBootstrapRequest.DoesNotExist:
            return JsonResponse({"error": "Guacamole bootstrap request not found"}, status=404)
        except _BootstrapViewError as err:
            return err.response
        return _status_response(bootstrap)


class GuacamoleBootstrapOpenView(MissionControlReadAPIView):
    """Render the compatibility opener for a Guacamole bootstrap."""

    permission_classes = [IsAuthenticatedSessionOrApiToken, HasMissionControlActor, _guacamole_read_permission()]

    def get(self, request: Request, request_id: UUID) -> HttpResponse:
        """Render an opener page that polls until the bootstrap URL is ready."""
        user = self.actor_user()
        try:
            GuacamoleBootstrapRequest.objects.only("id").get(pk=request_id, user_id=_authenticated_user_id(user))
        except GuacamoleBootstrapRequest.DoesNotExist:
            return HttpResponse("Guacamole session request not found.", status=404, content_type="text/plain")
        except _BootstrapViewError as err:
            return err.response

        status_url_name = _guacamole_bootstrap_url_names(request).get(
            "status_url_name",
            "mission_control:guacamole_bootstrap_status",
        )
        status_url = reverse(status_url_name, kwargs={"request_id": request_id})
        html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Opening session</title>
</head>
<body>
  <p id="status">Opening session...</p>
  <script>
    const statusUrl = {status_url!r};
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


def _range_bootstrap_response(
    *,
    request: Request,
    user: User,
    protocol: str,
    target_id: str,
    build_url: Callable[[], str],
) -> JsonResponse:
    """Create a bootstrap response with canonical route names when applicable."""
    return _guacamole_bootstrap_response(
        user=user,
        protocol=protocol,
        target_id=target_id,
        **_guacamole_bootstrap_url_names(request),
        build_url=build_url,
    )


def _status_response(bootstrap: GuacamoleBootstrapRequest) -> JsonResponse:
    """Return a JSON status response for a Guacamole bootstrap record."""
    payload: dict[str, str | int] = {"request_id": str(bootstrap.id), "status": bootstrap.status}
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
            payload["url"] = url
        else:
            payload["error"] = "Guacamole session link is no longer available"
            status_code = 410
    elif bootstrap.status == GuacamoleBootstrapRequest.Status.FAILED:
        payload["error"] = bootstrap.error_message or "Guacamole session bootstrap failed"
        status_code = bootstrap.error_status_code
    else:
        retry_after = True

    response = JsonResponse(payload, status=status_code)
    if retry_after:
        response["Retry-After"] = "1"
    return response


def _clear_parked_url(bootstrap: GuacamoleBootstrapRequest) -> None:
    """Remove a parked result URL once it can no longer be consumed."""
    if bootstrap.result_url:
        bootstrap.result_url = ""
        bootstrap.save(update_fields=("result_url", "updated_at"))


def _range_logger() -> Logger:
    """Resolve the shared Mission Control logger used by legacy Guacamole code."""
    from mission_control.views._common import _logger

    return _logger()
