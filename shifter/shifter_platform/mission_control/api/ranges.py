"""Range and catalog DRF views for Mission Control."""

from __future__ import annotations

from typing import Any, cast

from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from mission_control.api._base import (
    MissionControlAPIView,
    MissionControlReadAPIView,
    _is_empty_legacy_body,
    _range_write_permission,
    _raw_request,
    _validated,
)
from mission_control.api.permissions import HasMissionControlActor, block_participant_lifecycle_permission
from mission_control.api.serializers import LaunchRangeSerializer, RangeLifecycleSerializer
from mission_control.utils import build_connection_urls
from mission_control.views._common import _audit_range_lifecycle, _logger, _pkg
from risk_register.models import AuditLog
from shared.aces.presentation import build_range_aces_projection, build_range_participant_runtime_projection
from shared.api.permissions import IsAuthenticatedSessionOrApiToken
from shared.errors import classify_user_message
from shared.exceptions import CMSError
from shared.log_sanitize import safe_log_value


class CurrentRangeView(MissionControlReadAPIView):
    """Return the current user's active range."""

    def get(self, request: Request) -> Response:
        """Return the active range and connection URLs for the request user."""
        active_range = _pkg().get_active_range(self.actor_user())
        if not active_range:
            return Response(
                {
                    "has_range": False,
                    "range": None,
                    "connection_urls": [],
                    "aces_projection": None,
                    "aces_participant_runtime": None,
                }
            )
        projection = build_range_aces_projection(active_range.request_id)
        participant_runtime = build_range_participant_runtime_projection(
            active_range.request_id, active_range.instances
        )
        return Response(
            {
                "has_range": True,
                "range": active_range.model_dump(mode="json"),
                "connection_urls": build_connection_urls(active_range.instances),
                "aces_projection": projection.to_payload() if projection else None,
                "aces_participant_runtime": participant_runtime.to_payload() if participant_runtime else None,
            }
        )


class LaunchRangeView(MissionControlAPIView):
    """Launch a new cyber range."""

    permission_classes = [
        IsAuthenticatedSessionOrApiToken,
        HasMissionControlActor,
        _range_write_permission(),
        block_participant_lifecycle_permission("launch"),
    ]

    def post(self, request: Request) -> Response:
        """Validate input and create a range for the authenticated actor."""
        if _is_empty_legacy_body(request):
            return Response({"error": "Invalid JSON"}, status=status.HTTP_400_BAD_REQUEST)

        data, error = _validated(self, LaunchRangeSerializer, request.data)
        if error is not None:
            return error
        assert data is not None

        user = self.actor_user()
        return self._launch_range(request, user, data)

    def _launch_range(self, request: Request, user: User, data: dict[str, Any]) -> Response:
        """Launch a range once the request body has passed serializer checks."""
        scenario = str(data.get("scenario", "basic"))
        valid_scenarios = {s["id"] for s in _pkg().cms_list_launchable_scenarios(user, "range_launch")}
        if scenario not in valid_scenarios:
            return self.bad_request("Invalid scenario")

        agents_by_os, agents_error = self._resolve_agents_by_os(user, data)
        if agents_error is not None:
            return agents_error

        return self._create_range(request, user, scenario, agents_by_os)

    def _resolve_agents_by_os(self, user: User, data: dict[str, Any]) -> tuple[dict[str, int] | None, Response | None]:
        """Resolve either the explicit agent map or a legacy single agent id."""
        agents_error: Response | None = None
        agents_by_os: dict[str, int] | None = None
        if "agents" in data:
            agents_by_os = cast(dict[str, int], data["agents"])
        else:
            agent_id = cast(int, data.get("agent_id"))
            try:
                agent = _pkg().cms_get_agent(user, agent_id)
            except CMSError as exc:
                _logger().exception("Agent lookup failed: user=%s agent_id=%s", user.pk, safe_log_value(agent_id))
                agents_error = self.bad_request(classify_user_message(str(exc), default="Agent not available"))
            else:
                os_type = "windows" if agent.os.slug == "windows" else "linux"
                agents_by_os = {os_type: agent_id}
        return agents_by_os, agents_error

    def _create_range(
        self,
        request: Request,
        user: User,
        scenario: str,
        agents_by_os: dict[str, int] | None,
    ) -> Response:
        """Create a range and record the launch audit event."""
        try:
            range_ctx = _pkg().cms_create_range(user, scenario, agents_by_os or {})
        except CMSError as exc:
            _logger().exception("Range creation failed: user=%s scenario=%s", user.pk, safe_log_value(scenario))
            text = str(exc).lower()
            if "already have" in text or "active range" in text:
                response_msg = "You already have an active range"
            else:
                response_msg = classify_user_message(str(exc), default="Range could not be launched")
            return self.bad_request(response_msg)

        _logger().info(
            "Range launched: user=%s request_id=%s agent=%s scenario=%s",
            safe_log_value(user.email),
            range_ctx.request_id,
            safe_log_value(range_ctx.agent_name),
            safe_log_value(scenario),
        )
        _audit_range_lifecycle(
            _raw_request(request),
            AuditLog.Action.PROVISION,
            range_request_id=str(range_ctx.request_id),
            extra_state={"scenario": scenario, "agents": agents_by_os},
        )
        return Response({"success": True, "range": range_ctx.model_dump(mode="json")})


class RangeLifecycleView(MissionControlAPIView):
    """Base class for range lifecycle mutations."""

    log_verb = ""
    audit_action = ""
    by_request_attr = ""
    by_id_attr = ""
    lifecycle_verb = ""

    def get_permissions(self) -> list[object]:
        """Append the lifecycle-verb participant permission to the base gates."""
        permissions = super().get_permissions()
        permissions.append(block_participant_lifecycle_permission(self.lifecycle_verb)())
        return permissions

    def post(self, request: Request) -> Response:
        """Run the configured range lifecycle service method."""
        import cms.services as cms_services_mod

        data, error = _validated(self, RangeLifecycleSerializer, request.data)
        if error is not None:
            return error
        assert data is not None

        user = self.actor_user()
        request_id = str(data["request_id"]) if data.get("request_id") else None
        range_id = data.get("range_id")
        try:
            if request_id:
                getattr(cms_services_mod, self.by_request_attr)(user, request_id)
                _logger().info(
                    "Range %s: user=%s request_id=%s",
                    self.log_verb,
                    safe_log_value(user.email),
                    safe_log_value(request_id),
                )
            else:
                getattr(cms_services_mod, self.by_id_attr)(user, range_id)
                _logger().info(
                    "Range %s: user=%s range_id=%s",
                    self.log_verb,
                    safe_log_value(user.email),
                    safe_log_value(range_id),
                )
        except CMSError as exc:
            _logger().exception(
                "Range %s failed: user=%s request_id=%s range_id=%s",
                self.log_verb,
                user.pk,
                safe_log_value(request_id),
                safe_log_value(range_id),
            )
            return self.bad_request(classify_user_message(str(exc), default="Range action could not be completed"))

        _audit_range_lifecycle(
            _raw_request(request),
            self.audit_action,
            range_id=range_id,
            range_request_id=request_id,
        )
        return Response({"success": True})


class CancelRangeView(RangeLifecycleView):
    """Cancel a pending or active range."""

    log_verb = "cancelled"
    audit_action = AuditLog.Action.CANCEL
    by_request_attr = "cancel_range_by_request_id"
    by_id_attr = "cancel_range"
    lifecycle_verb = "cancel"


class DestroyRangeView(RangeLifecycleView):
    """Destroy a range."""

    log_verb = "destroyed"
    audit_action = AuditLog.Action.DEPROVISION
    by_request_attr = "destroy_range_by_request_id"
    by_id_attr = "destroy_range"
    lifecycle_verb = "destroy"


class PauseRangeView(RangeLifecycleView):
    """Pause a range."""

    log_verb = "paused"
    audit_action = AuditLog.Action.PAUSE
    by_request_attr = "pause_range_by_request_id"
    by_id_attr = "pause_range"
    lifecycle_verb = "pause"


class ResumeRangeView(RangeLifecycleView):
    """Resume a paused range."""

    log_verb = "resumed"
    audit_action = AuditLog.Action.RESUME
    by_request_attr = "resume_range_by_request_id"
    by_id_attr = "resume_range"
    lifecycle_verb = "resume"


class AgentListView(MissionControlReadAPIView):
    """Return the authenticated user's agent list."""

    def get(self, request: Request) -> Response:
        """Return agents available to the authenticated actor."""
        return Response({"agents": _pkg().cms_list_agents(self.actor_user())})


class ScenarioListView(MissionControlReadAPIView):
    """Return available range scenarios."""

    def get(self, request: Request) -> Response:
        """Return scenarios available to the authenticated actor."""
        scenarios: list[dict[str, Any]] = _pkg().cms_list_launchable_scenarios(self.actor_user(), "range_launch")
        return Response({"scenarios": scenarios})
