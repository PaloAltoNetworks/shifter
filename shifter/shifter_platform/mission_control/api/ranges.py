"""Range and catalog DRF views for Mission Control."""

from __future__ import annotations

from typing import Any, cast

from django.contrib.auth.models import User
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework.request import Request
from rest_framework.response import Response

from cms.services import list_mission_control_range_history
from mission_control.api._base import (
    MissionControlAPIView,
    MissionControlReadAPIView,
    _range_write_permission,
    _raw_request,
    _validated,
)
from mission_control.api.permissions import HasMissionControlActor, block_participant_lifecycle_permission
from mission_control.api.rate_limit import RangeLaunchRateThrottle
from mission_control.api.serializers import (
    AgentListResponseSerializer,
    CurrentRangeResponseSerializer,
    LaunchRangeResponseSerializer,
    LaunchRangeSerializer,
    RangeHistoryResponseSerializer,
    RangeHistorySerializer,
    RangeLeaseResponseSerializer,
    RangeLifecycleSerializer,
    ScenarioListResponseSerializer,
    SuccessResponseSerializer,
)
from mission_control.utils import build_connection_urls
from mission_control.views._common import _audit_range_lifecycle, _logger, _pkg
from shared.aces.presentation import build_range_aces_projection, build_range_participant_runtime_projection
from shared.api.permissions import IsAuthenticatedSessionOrApiToken
from shared.api.schema import ApiErrorSerializer
from shared.audit import AuditAction
from shared.auth import is_ctf_participant_only
from shared.errors import classify_user_message
from shared.exceptions import CMSError
from shared.log_sanitize import safe_log_value


class CurrentRangeView(MissionControlReadAPIView):
    """Return the current user's active range."""

    @extend_schema(responses=CurrentRangeResponseSerializer, operation_id="api_v1_mission_control_range_retrieve")
    def get(self, request: Request) -> Response:
        """Return the active range and connection URLs for the request user."""
        actor = self.actor_user()
        active_range = _pkg().get_active_range(actor)
        if not active_range:
            return Response(
                {
                    "has_range": False,
                    "range": None,
                    "connection_urls": [],
                    "aces_projection": None,
                    "aces_participant_runtime": None,
                    "lifecycle": None,
                    "vpn_profile_available": False,
                }
            )
        # CTF participants only see Kali (attacker) instances — mirrors the
        # ``mission_control.context_processors.active_range`` filter so this
        # canonical DRF read matches the legacy template-rendered behavior.
        if is_ctf_participant_only(actor):
            active_range.instances = [inst for inst in active_range.instances if inst.os_type == "kali"]
        projection = build_range_aces_projection(active_range.request_id)
        participant_runtime = build_range_participant_runtime_projection(
            active_range.request_id, active_range.instances
        )
        lease = _pkg().get_mission_control_range_lease(actor)
        return Response(
            {
                "has_range": True,
                "range": active_range.model_dump(mode="json"),
                "connection_urls": build_connection_urls(active_range.instances),
                "aces_projection": projection.to_payload() if projection else None,
                "aces_participant_runtime": participant_runtime.to_payload() if participant_runtime else None,
                "lifecycle": lease.to_payload() if lease else None,
                "vpn_profile_available": _pkg().has_mission_control_openvpn_profile(actor),
            }
        )


class ExtendRangeLeaseView(MissionControlAPIView):
    """Extend the authenticated actor's Mission Control range by one fixed increment."""

    permission_classes = [
        IsAuthenticatedSessionOrApiToken,
        HasMissionControlActor,
        _range_write_permission(),
        block_participant_lifecycle_permission("extend"),
    ]

    @extend_schema(
        request=None,
        responses={
            200: RangeLeaseResponseSerializer,
            400: ApiErrorSerializer,
            404: ApiErrorSerializer,
            409: ApiErrorSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        """Extend only the server-owned lease; caller timestamps are forbidden."""
        if request.body or request.query_params:
            response = self.error_response(
                code="invalid",
                message="Range extension requests must not include a body or query parameters.",
                status_code=400,
            )
        else:
            from cms.services import RangeLeaseConflict, RangeLeaseNotFound

            try:
                lease = _pkg().cms_extend_mission_control_range(self.actor_user())
            except RangeLeaseNotFound:
                response = self.not_found("Range not found")
            except RangeLeaseConflict:
                response = self.error_response(
                    code="range_extension_unavailable",
                    message="Range cannot be extended.",
                    status_code=409,
                )
            else:
                response = Response({"lifecycle": lease.to_payload()})
        return response


class LaunchRangeView(MissionControlAPIView):
    """Launch a new cyber range."""

    permission_classes = [
        IsAuthenticatedSessionOrApiToken,
        HasMissionControlActor,
        _range_write_permission(),
        block_participant_lifecycle_permission("launch"),
    ]
    # Backpressure (#322): per-actor + fleet admission budget, before CMS.
    throttle_classes = [RangeLaunchRateThrottle]

    @extend_schema(
        request=LaunchRangeSerializer,
        responses=LaunchRangeResponseSerializer,
        operation_id="api_v1_mission_control_range_launch",
    )
    def post(self, request: Request) -> Response:
        """Validate input and create a range for the authenticated actor."""
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
            AuditAction.PROVISION,
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


@extend_schema_view(
    post=extend_schema(
        request=RangeLifecycleSerializer,
        responses=SuccessResponseSerializer,
        operation_id="api_v1_mission_control_range_cancel",
    )
)
class CancelRangeView(RangeLifecycleView):
    """Cancel a pending or active range."""

    log_verb = "cancelled"
    audit_action = AuditAction.CANCEL
    by_request_attr = "cancel_range_by_request_id"
    by_id_attr = "cancel_range"
    lifecycle_verb = "cancel"


@extend_schema_view(
    post=extend_schema(
        request=RangeLifecycleSerializer,
        responses=SuccessResponseSerializer,
        operation_id="api_v1_mission_control_range_destroy",
    )
)
class DestroyRangeView(RangeLifecycleView):
    """Destroy a range."""

    log_verb = "destroyed"
    audit_action = AuditAction.DEPROVISION
    by_request_attr = "destroy_range_by_request_id"
    by_id_attr = "destroy_range"
    lifecycle_verb = "destroy"


@extend_schema_view(
    post=extend_schema(
        request=RangeLifecycleSerializer,
        responses=SuccessResponseSerializer,
        operation_id="api_v1_mission_control_range_pause",
    )
)
class PauseRangeView(RangeLifecycleView):
    """Pause a range."""

    log_verb = "paused"
    audit_action = AuditAction.PAUSE
    by_request_attr = "pause_range_by_request_id"
    by_id_attr = "pause_range"
    lifecycle_verb = "pause"


@extend_schema_view(
    post=extend_schema(
        request=RangeLifecycleSerializer,
        responses=SuccessResponseSerializer,
        operation_id="api_v1_mission_control_range_resume",
    )
)
class ResumeRangeView(RangeLifecycleView):
    """Resume a paused range."""

    log_verb = "resumed"
    audit_action = AuditAction.RESUME
    by_request_attr = "resume_range_by_request_id"
    by_id_attr = "resume_range"
    lifecycle_verb = "resume"


class AgentListView(MissionControlReadAPIView):
    """Return the authenticated user's agent list."""

    @extend_schema(responses=AgentListResponseSerializer, operation_id="api_v1_mission_control_agents_list")
    def get(self, request: Request) -> Response:
        """Return agents available to the authenticated actor."""
        return Response({"agents": _pkg().cms_list_agents(self.actor_user())})


class ScenarioListView(MissionControlReadAPIView):
    """Return available range scenarios."""

    @extend_schema(responses=ScenarioListResponseSerializer, operation_id="api_v1_mission_control_scenarios_list")
    def get(self, request: Request) -> Response:
        """Return scenarios available to the authenticated actor."""
        scenarios: list[dict[str, Any]] = _pkg().cms_list_launchable_scenarios(self.actor_user(), "range_launch")
        return Response({"scenarios": scenarios})


class RangeHistoryView(MissionControlReadAPIView):
    """Return the authenticated user's range history (#1370).

    Backed by ``cms.services.list_mission_control_range_history``, the
    product-scoped history query: it reads through ``all_objects`` so
    soft-deleted terminal ranges (DESTROYED/FAILED, the rows a history view
    exists to show) are INCLUDED, and scopes to
    ``range_source == MISSION_CONTROL`` so CTF-sourced ranges never leak into
    this Mission Control surface. It returns raw ``RangeInstance`` rows
    (newest first), which are projected into ``RangeHistorySerializer``
    explicitly here rather than reusing ``RangePresentationSerializer`` — a
    history row has no hydrated ``instances``/``agent_name``/computed-status
    fields, only the durable identifiers, status, provenance, and timestamps.
    """

    @extend_schema(responses=RangeHistoryResponseSerializer, operation_id="api_v1_mission_control_ranges_list")
    def get(self, request: Request) -> Response:
        """Return the authenticated actor's Mission Control range history, newest first."""
        ranges = list_mission_control_range_history(self.actor_user())
        serializer = RangeHistorySerializer(
            [
                {
                    # ``range_instance.request_id`` is the Django FK shadow
                    # attribute (the related ``Request`` row's integer pk) —
                    # NOT the durable UUID correlation key. That key lives on
                    # the related row as ``Request.request_id``.
                    "request_id": range_instance.request.request_id if range_instance.request else None,
                    "range_id": range_instance.range_id,
                    "scenario_id": range_instance.scenario_id,
                    "status": range_instance.status,
                    "range_source": range_instance.range_source,
                    "created_at": range_instance.created_at,
                    "updated_at": range_instance.updated_at,
                    "deleted_at": range_instance.deleted_at,
                }
                for range_instance in ranges
            ],
            many=True,
        )
        return Response({"ranges": serializer.data})
