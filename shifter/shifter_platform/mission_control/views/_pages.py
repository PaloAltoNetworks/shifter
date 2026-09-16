"""Page-rendering and agent-management views."""

from __future__ import annotations

import logging

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from cms.services import (
    delete_agent as cms_delete_agent,
)
from cms.services import (
    get_allowed_extensions,
)
from cms.services import (
    list_agents as cms_list_agents,
)
from shared.exceptions import AssetError, CMSError
from shared.log_sanitize import safe_log_value

from ._common import _get_user

logger = logging.getLogger(__name__)


@login_required
@require_GET
def dashboard(request: HttpRequest) -> HttpResponse:
    """Ranges page - launch and manage cyber ranges."""
    from django.middleware.csrf import get_token
    from django.urls import reverse

    from shared.auth import is_ctf_participant_only

    # Build the client bootstrap payload server-side and hand it to the template
    # via ``json_script`` so the template stays within SonarCloud's inline-JS
    # length limit (Web:LongJavaScriptCheck). dashboard-init.js reads it from the
    # ``#dashboard-config`` element.
    context = {
        "page_title": "Ranges",
        "active_nav": "ranges",
        "dashboard_config": {
            "csrfToken": get_token(request),
            "rangeUrl": reverse("v1:mission_control:range-current"),
            "launchUrl": reverse("v1:mission_control:range-launch"),
            "cancelUrl": reverse("v1:mission_control:range-cancel"),
            "destroyUrl": reverse("v1:mission_control:range-destroy"),
            "pauseUrl": reverse("v1:mission_control:range-pause"),
            "resumeUrl": reverse("v1:mission_control:range-resume"),
            "agentsUrl": reverse("v1:mission_control:agents-list"),
            "scenariosUrl": reverse("v1:mission_control:scenarios-list"),
            "loginUrl": reverse("dashboard_router"),
            "provisioningTimeoutMs": django_settings.PROVISIONING_TIMEOUT_MS,
            "viewOnly": is_ctf_participant_only(request.user),
        },
    }
    return render(request, "mission_control/dashboard.html", context)


@login_required
@require_GET
def agents(request: HttpRequest) -> HttpResponse:
    """Agent management - upload and manage XDR/XSIAM agents."""
    context = {
        "page_title": "Agents",
        "active_nav": "agents",
        "agents": cms_list_agents(_get_user(request)),
        "allowed_extensions": ", ".join(get_allowed_extensions()),
    }
    return render(request, "mission_control/agents.html", context)


@login_required
@require_POST
def delete_agent(request: HttpRequest, agent_id: int) -> HttpResponse:
    """Handle agent deletion (soft delete)."""
    user = _get_user(request)
    try:
        cms_delete_agent(user, agent_id)
        messages.success(request, "Agent deleted.")
        logger.info("Agent deleted: user=%s agent_id=%s", safe_log_value(user.email), safe_log_value(agent_id))
    except (CMSError, AssetError) as e:
        messages.error(request, str(e))
        logger.exception(
            "Agent delete error: user=%s agent_id=%s",
            safe_log_value(user.email),
            safe_log_value(agent_id),
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
            "rdpUrl": reverse("v1:mission_control:guacamole-rdp-url"),
            "sshUrl": reverse("v1:mission_control:guacamole-ssh-url"),
            "csrfToken": get_token(request),
        },
    }
    return render(request, "mission_control/terminal.html", context)


@login_required
@require_GET
def settings(request: HttpRequest) -> HttpResponse:
    """Account settings."""
    context = {
        "page_title": "Settings",
        "active_nav": "settings",
    }
    return render(request, "mission_control/settings.html", context)


@login_required
@require_GET
def help_page(request: HttpRequest) -> HttpResponse:
    """Help and documentation."""
    context = {
        "page_title": "Help",
        "active_nav": "help",
        "support_email": django_settings.SHIFTER_SUPPORT_EMAIL,
    }
    return render(request, "mission_control/help.html", context)


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
    return render(request, "mission_control/walkthrough.html", context)
