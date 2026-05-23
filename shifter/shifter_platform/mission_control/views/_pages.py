"""Page-rendering and agent-management views."""

from __future__ import annotations

import logging

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_GET, require_POST

from shared.exceptions import AssetError, CMSError

from ._common import (
    _cms_delete_agent_via_pkg,
    _cms_list_agents_via_pkg,
    _get_allowed_extensions_via_pkg,
    _get_user,
    _render_via_pkg,
)

logger = logging.getLogger(__name__)


@login_required
@require_GET
def dashboard(request: HttpRequest) -> HttpResponse:
    """Ranges page - launch and manage cyber ranges."""
    context = {
        "page_title": "Ranges",
        "active_nav": "ranges",
        "provisioning_timeout_ms": django_settings.PROVISIONING_TIMEOUT_MS,
    }
    return _render_via_pkg(request, "mission_control/dashboard.html", context)


@login_required
@require_GET
def agents(request: HttpRequest) -> HttpResponse:
    """Agent management - upload and manage XDR/XSIAM agents."""
    context = {
        "page_title": "Agents",
        "active_nav": "agents",
        "agents": _cms_list_agents_via_pkg(_get_user(request)),
        "allowed_extensions": ", ".join(_get_allowed_extensions_via_pkg()),
    }
    return _render_via_pkg(request, "mission_control/agents.html", context)


@login_required
@require_POST
def delete_agent(request: HttpRequest, agent_id: int) -> HttpResponse:
    """Handle agent deletion (soft delete)."""
    user = _get_user(request)
    try:
        _cms_delete_agent_via_pkg(user, agent_id)
        messages.success(request, "Agent deleted.")
        logger.info("Agent deleted: user=%s agent_id=%s", user.email, agent_id)
    except (CMSError, AssetError) as e:
        messages.error(request, str(e))
        logger.error(
            "Agent delete error: user=%s agent_id=%s error=%s",
            user.email,
            agent_id,
            str(e),
        )

    return redirect("mission_control:agents")


@login_required
@require_GET
def terminal(request: HttpRequest) -> HttpResponse:
    """Terminal - SSH access to range instances.

    Uses active_range and has_active_range from context processor.
    Template accesses active_range.range_id for WebSocket connection.
    OS types for RDP buttons are accessed via active_range.attacker_instance/victim_instances.
    """
    from django.middleware.csrf import get_token
    from django.urls import reverse

    context = {
        "page_title": "Terminal",
        "active_nav": "terminal",
        "terminal_guacamole_config": {
            "rdpUrl": reverse("mission_control:guacamole_rdp_url"),
            "sshUrl": reverse("mission_control:guacamole_ssh_url"),
            "csrfToken": get_token(request),
        },
    }
    return _render_via_pkg(request, "mission_control/terminal.html", context)


@login_required
@require_GET
def settings(request: HttpRequest) -> HttpResponse:
    """Account settings."""
    context = {
        "page_title": "Settings",
        "active_nav": "settings",
    }
    return _render_via_pkg(request, "mission_control/settings.html", context)


@login_required
@require_GET
def help_page(request: HttpRequest) -> HttpResponse:
    """Help and documentation."""
    context = {
        "page_title": "Help",
        "active_nav": "help",
        "support_email": django_settings.SHIFTER_SUPPORT_EMAIL,
    }
    return _render_via_pkg(request, "mission_control/help.html", context)


@login_required
@require_GET
def walkthrough(request: HttpRequest) -> HttpResponse:
    """Participant launch page for the standalone CTFd platform."""
    context = {
        "page_title": "CTFd",
        "active_nav": "walkthrough",
        "ctfd_url": getattr(
            django_settings,
            "CTFD_PLATFORM_URL",
            "https://ctf.shifter.example.com/login",
        ),
    }
    return _render_via_pkg(request, "mission_control/walkthrough.html", context)
