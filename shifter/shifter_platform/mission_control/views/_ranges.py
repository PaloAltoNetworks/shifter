"""Range lifecycle API views (get / launch / cancel / destroy / pause / resume)."""

from __future__ import annotations

import json
from typing import Any

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET, require_POST

from mission_control.utils import build_connection_urls
from risk_register.models import AuditLog
from shared.errors import UserFacingError
from shared.exceptions import CMSError
from shared.log_sanitize import safe_log_value

from ._common import _audit_range_lifecycle, _get_user, _logger, _pkg


class _RangeError(Exception):
    """Internal exception carrying a JsonResponse for early-return guards."""

    def __init__(self, response: JsonResponse) -> None:
        super().__init__()
        self.response = response


def _parse_json_body(request: HttpRequest) -> dict[str, Any]:
    """Parse the JSON body or raise ``_RangeError``."""
    try:
        return json.loads(request.body)
    except json.JSONDecodeError as e:
        raise _RangeError(JsonResponse({"error": "Invalid JSON"}, status=400)) from e


@login_required
@require_GET
def get_range(request: HttpRequest) -> JsonResponse:
    """
    Get the current user's active range.

    Response (JSON):
        - has_range: true/false
        - range: RangeContext object (if exists)
    """
    # Late-bound: tests patch ``views.get_active_range``.
    active_range = _pkg().get_active_range(_get_user(request))

    if not active_range:
        return JsonResponse({"has_range": False, "range": None, "connection_urls": []})

    return JsonResponse(
        {
            "has_range": True,
            "range": active_range.model_dump(mode="json"),
            "connection_urls": build_connection_urls(active_range.instances),
        }
    )


def _resolve_launch_agents(user: User, data: dict[str, Any]) -> dict[str, int]:
    """Resolve the ``agents`` mapping for ``launch_range`` or raise ``_RangeError``."""
    if "agents" in data:
        return data["agents"]
    if "agent_id" in data:
        agent_id = data["agent_id"]
        if not agent_id:
            raise _RangeError(JsonResponse({"error": "agent_id is required"}, status=400))
        try:
            agent = _pkg().cms_get_agent(user, agent_id)
        except CMSError as e:
            raise _RangeError(JsonResponse({"error": UserFacingError(str(e)).user_message}, status=400)) from e
        os_type = "windows" if agent.os.slug == "windows" else "linux"
        return {os_type: agent_id}
    raise _RangeError(JsonResponse({"error": "Either 'agents' or 'agent_id' is required"}, status=400))


@login_required
@require_POST
def launch_range(request: HttpRequest) -> JsonResponse:
    """
    Launch a new cyber range.

    Request body (JSON):
        New format:
        - agents: Dict mapping OS type to agent ID, e.g. {"windows": 123}
        - scenario: Scenario type (basic, ad_attack_lab). Defaults to basic.

        Legacy format (backward compatible):
        - agent_id: ID of agent to use for victim instances
        - scenario: Scenario type (basic, ad_attack_lab). Defaults to basic.

    Response (JSON):
        - success: true
        - range: Range object
    """
    user = _get_user(request)
    try:
        data = _parse_json_body(request)
        scenario = data.get("scenario", "basic")
        valid_scenarios = {s["id"] for s in _pkg().cms_list_scenarios(user)}
        if scenario not in valid_scenarios:
            raise _RangeError(JsonResponse({"error": "Invalid scenario"}, status=400))
        agents_by_os = _resolve_launch_agents(user, data)
        try:
            range_ctx = _pkg().cms_create_range(user, scenario, agents_by_os)
        except CMSError as e:
            raise _RangeError(JsonResponse({"error": UserFacingError(str(e)).user_message}, status=400)) from e
    except _RangeError as err:
        return err.response

    _logger().info(
        "Range launched: user=%s request_id=%s agent=%s scenario=%s",
        safe_log_value(user.email),
        range_ctx.request_id,
        safe_log_value(range_ctx.agent_name),
        safe_log_value(scenario),
    )
    _audit_range_lifecycle(
        request,
        AuditLog.Action.PROVISION,
        range_request_id=str(range_ctx.request_id),
        extra_state={"scenario": scenario, "agents": agents_by_os},
    )
    return JsonResponse(
        {
            "success": True,
            "range": range_ctx.model_dump(mode="json"),
        }
    )


def _dispatch_range_lifecycle(
    request: HttpRequest,
    *,
    log_verb: str,
    audit_action: str,
    by_request_attr: str,
    by_id_attr: str,
) -> JsonResponse:
    """Shared cancel/destroy/pause/resume dispatcher.

    The CMS callables are looked up at call time by attribute name on
    ``cms.services`` so ``patch("cms.services.<name>")`` continues to work.
    """
    import cms.services as cms_services_mod

    user = _get_user(request)
    try:
        data = _parse_json_body(request)
        request_id = data.get("request_id")
        range_id = data.get("range_id")
        if not request_id and not range_id:
            raise _RangeError(JsonResponse({"error": "request_id or range_id is required"}, status=400))
        try:
            if request_id:
                getattr(cms_services_mod, by_request_attr)(user, request_id)
                _logger().info(
                    "Range %s: user=%s request_id=%s",
                    log_verb,
                    safe_log_value(user.email),
                    safe_log_value(request_id),
                )
            else:
                getattr(cms_services_mod, by_id_attr)(user, range_id)
                _logger().info(
                    "Range %s: user=%s range_id=%s",
                    log_verb,
                    safe_log_value(user.email),
                    safe_log_value(range_id),
                )
        except CMSError as e:
            raise _RangeError(JsonResponse({"error": UserFacingError(str(e)).user_message}, status=400)) from e
    except _RangeError as err:
        return err.response

    _audit_range_lifecycle(
        request,
        audit_action,
        range_id=range_id,
        range_request_id=request_id,
    )
    return JsonResponse({"success": True})


@login_required
@require_POST
def cancel_range(request: HttpRequest) -> JsonResponse:
    """
    Cancel a provisioning range.

    Request body (JSON):
        - request_id: UUID of the request (preferred)
        - range_id: ID of range to cancel (legacy, deprecated)

    Only works for ranges in PENDING or PROVISIONING status.
    """
    return _dispatch_range_lifecycle(
        request,
        log_verb="cancelled",
        audit_action=AuditLog.Action.CANCEL,
        by_request_attr="cancel_range_by_request_id",
        by_id_attr="cancel_range",
    )


@login_required
@require_POST
def destroy_range(request: HttpRequest) -> JsonResponse:
    """
    Destroy an active, paused, or failed range.

    Request body (JSON):
        - request_id: UUID of the request (preferred)
        - range_id: ID of range to destroy (legacy, deprecated)

    Sets status to DESTROYING and triggers async resource cleanup.
    """
    return _dispatch_range_lifecycle(
        request,
        log_verb="destroyed",
        audit_action=AuditLog.Action.DEPROVISION,
        by_request_attr="destroy_range_by_request_id",
        by_id_attr="destroy_range",
    )


@login_required
@require_POST
def pause_range(request: HttpRequest) -> JsonResponse:
    """
    Pause an active range.

    Request body (JSON):
        - request_id: UUID of the request (preferred)
        - range_id: ID of range to pause (legacy, deprecated)

    Sets status to PAUSING and triggers async instance stop.
    """
    return _dispatch_range_lifecycle(
        request,
        log_verb="paused",
        audit_action=AuditLog.Action.PAUSE,
        by_request_attr="pause_range_by_request_id",
        by_id_attr="pause_range",
    )


@login_required
@require_POST
def resume_range(request: HttpRequest) -> JsonResponse:
    """
    Resume a paused range.

    Request body (JSON):
        - request_id: UUID of the request (preferred)
        - range_id: ID of range to resume (legacy, deprecated)

    Sets status to RESUMING and triggers async instance start.
    """
    return _dispatch_range_lifecycle(
        request,
        log_verb="resumed",
        audit_action=AuditLog.Action.RESUME,
        by_request_attr="resume_range_by_request_id",
        by_id_attr="resume_range",
    )


@login_required
@require_GET
def list_agents(request: HttpRequest) -> JsonResponse:
    """
    Get user's agents.

    Response (JSON):
        - agents: List of {id, name, os_name, os_slug, file_size_mb, original_filename, created_at}

    The os_slug field allows frontend to filter agents by OS type
    (e.g., 'windows' for DC agent dropdown in AD scenarios).
    """
    agents = _pkg().cms_list_agents(_get_user(request))
    return JsonResponse({"agents": agents})


@login_required
@require_GET
def list_scenarios(request: HttpRequest) -> JsonResponse:
    """
    Get available scenarios with agent requirements.

    Response (JSON):
        - scenarios: List of scenario dicts with agent_requirements field
    """
    scenarios: list[dict[str, Any]] = _pkg().cms_list_scenarios(_get_user(request))
    return JsonResponse({"scenarios": scenarios})
