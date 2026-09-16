"""Context processors for mission_control app."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, cast

from django.conf import settings
from django.http import HttpRequest

from cms.services import get_active_range, get_scenario, has_ready_active_range
from mission_control.utils import build_connection_urls
from shared.enums import RangeSource
from shared.schemas import InstanceContext, RangeContext

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)

# The terminal page is the only render that consumes the full active-range
# payload (instances, runtime IP overlay, connection URLs, terminal JSON).
# Every other authenticated page needs only the cheap ``has_active_range``
# indicator, so the depth is selected server-side from the resolved URL pattern
# (never from client input) — the ``nav`` / ``terminal_full`` seam from #898.
_TERMINAL_VIEW_NAME = "mission_control:terminal"


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

    Centralizes the unauthenticated and reachable service-failure branches of
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

    # Instance visibility is a domain policy (#483): CTF registers a per-event
    # filter through the shared seam; other users see everything.
    from shared.range_visibility import filter_visible_instances

    range_context.instances = filter_visible_instances(request.user, range_context.instances)

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


def _needs_terminal_payload(request: HttpRequest) -> bool:
    """True only for the terminal render, the one page that reads the full payload.

    Derived from the resolved URL pattern (server-owned), never from a query
    string, header, or other client-selectable input.
    """
    match = request.resolver_match
    return bool(match and match.view_name == _TERMINAL_VIEW_NAME)


def _range_source_for_user(user: User) -> RangeSource:
    """Select the product source whose active range should back the UI."""
    from shared.auth import is_ctf_participant_only

    if is_ctf_participant_only(user):
        return RangeSource.CTF
    return RangeSource.MISSION_CONTROL


def _nav_active_range(request: HttpRequest) -> dict[str, Any]:
    """``nav``-tier context: the cheap ``has_active_range`` sidebar indicator only.

    Avoids the terminal-only FK joins, runtime IP overlay, scenario lookup, and
    terminal JSON construction on every non-terminal authenticated render (#898).
    """
    from django.contrib.auth.models import User

    user = cast(User, request.user)
    context = _empty_active_range_context()
    try:
        context["has_active_range"] = has_ready_active_range(user, _range_source_for_user(user))
    except Exception:
        logger.exception("Error computing has_active_range for user_id=%s", user.id)
    return context


def active_range(request: HttpRequest) -> dict[str, Any]:
    """
    Add active range information to template context.

    Uses CMS service to get the user's active range as a RangeContext.

    The full payload is built only for the terminal render; every other
    authenticated page gets the cheap ``has_active_range`` indicator (#898).

    Provides:
        - has_active_range: Boolean indicating if user has a ready range
        - active_range: The user's active RangeContext (or None)
        - terminal_instances: json_script-safe per-instance payload for terminal.js
    """
    if not request.user.is_authenticated:
        return _empty_active_range_context()
    if _needs_terminal_payload(request):
        return _safe_active_range(request)
    return _nav_active_range(request)


def _safe_active_range(request: HttpRequest) -> dict[str, Any]:
    """Resolve the active range with guaranteed fall-back on any service error."""
    from django.contrib.auth.models import User

    user = cast(User, request.user)
    user_id = user.id
    try:
        range_context = get_active_range(user, _range_source_for_user(user))
    except Exception:
        logger.exception("Error in active_range context processor for user_id=%s", user_id)
        return _empty_active_range_context()
    return _build_active_range_context(range_context, request, user_id)


def docs_site_url(_request: HttpRequest) -> dict[str, Any]:
    """Expose the public documentation site URL to templates (ADR-038).

    Django calls context processors with the request positionally; this one does
    not need it. Templates link out to the hosted mkdocs site instead of
    hardcoding the absolute URL; the value is configured in settings.DOCS_SITE_URL.
    """
    return {"DOCS_SITE_URL": settings.DOCS_SITE_URL}
