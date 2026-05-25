"""Context processors for mission_control app."""

import logging
from collections.abc import Iterable
from typing import Any, cast

from django.conf import settings
from django.http import HttpRequest

from cms.services import get_active_range, get_scenario
from mission_control.utils import build_connection_urls
from shared.auth import is_ctf_participant_only
from shared.schemas import InstanceContext, RangeContext

logger = logging.getLogger(__name__)


def terminal_cdn_assets(_request: HttpRequest) -> dict[str, Any]:
    """Expose the centralised TERMINAL_CDN_ASSETS map to every template.

    The terminal page renders <link>/<script> tags from this map so the
    template never hard-codes absolute CDN URIs (Sonar Web:S1829).
    """
    return {"terminal_cdn_assets": getattr(settings, "TERMINAL_CDN_ASSETS", {})}


def _terminal_instances_payload(instances: Iterable[InstanceContext]) -> list[dict[str, Any]]:
    """Project InstanceContext rows into the json_script-safe dict shape consumed by terminal.js."""
    return [
        {
            "uuid": inst.uuid,
            "role": inst.role,
            "osType": inst.os_type,
            "name": inst.name or inst.role,
            "privateIp": inst.private_ip,
        }
        for inst in instances
    ]


def _empty_active_range_context() -> dict[str, Any]:
    """Return the shared "no active range" context payload.

    Centralizes the unauthenticated, invalid-type, and exception branches of
    ``active_range`` so the function stays under the Sonar return-count gate
    and so all empty payloads share one shape.
    """
    return {
        "has_active_range": False,
        "active_range": None,
        "connection_urls": [],
        "scenario_name": None,
        "terminal_instances": [],
    }


def _build_active_range_context(
    range_context: RangeContext | None, request: HttpRequest, user_id: object
) -> dict[str, Any]:
    """Compose the populated active_range context dict from a resolved RangeContext."""
    if range_context is None:
        logger.info("active_range context processor: no active range for user_id=%s", user_id)
        return {
            "has_active_range": False,
            "active_range": None,
            "connection_urls": [],
            "scenario_name": None,
            "terminal_instances": [],
        }

    is_ready = range_context.is_ready
    logger.info(
        "active_range context processor: found range for user_id=%s, status=%s, is_ready=%s",
        user_id,
        range_context.status,
        is_ready,
    )

    # CTF participants only see Kali (attacker) instances
    if is_ctf_participant_only(request.user):
        range_context.instances = [inst for inst in range_context.instances if inst.os_type == "kali"]

    scenario_name = None
    if range_context.scenario_id:
        try:
            scenario = get_scenario(range_context.scenario_id)
            scenario_name = scenario.get("name", range_context.scenario_id)
        except Exception:
            logger.warning("Could not look up scenario name for scenario_id=%s", range_context.scenario_id)
            scenario_name = range_context.scenario_id

    return {
        "has_active_range": is_ready,
        "active_range": range_context,
        "connection_urls": build_connection_urls(range_context.instances),
        "scenario_name": scenario_name,
        "terminal_instances": _terminal_instances_payload(range_context.instances),
    }


def active_range(request: HttpRequest) -> dict[str, Any]:
    """
    Add active range information to template context.

    Uses CMS service to get the user's active range as a RangeContext.

    Provides:
        - has_active_range: Boolean indicating if user has a ready range
        - active_range: The user's active RangeContext (or None)
        - terminal_instances: json_script-safe per-instance payload for terminal.js
    """
    if not request.user.is_authenticated:
        return _empty_active_range_context()
    return _safe_active_range(request)


def _safe_active_range(request: HttpRequest) -> dict[str, Any]:
    """Resolve the active range with guaranteed fall-back on any service error."""
    from django.contrib.auth.models import User

    user = cast(User, request.user)
    user_id = user.id
    try:
        range_context = get_active_range(user)
    except Exception:
        logger.exception("Error in active_range context processor for user_id=%s", user_id)
        return _empty_active_range_context()

    if range_context is not None and not isinstance(range_context, RangeContext):
        logger.error(
            "active_range context processor: get_active_range returned invalid type %s for user_id=%s",
            type(range_context).__name__,
            user_id,
        )
        return _empty_active_range_context()
    return _build_active_range_context(range_context, request, user_id)
