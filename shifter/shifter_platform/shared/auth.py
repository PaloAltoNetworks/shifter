"""Access control utilities for Shifter views."""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable

from django.conf import settings
from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

logger = logging.getLogger(__name__)

THREAT_RESEARCH_GROUP = "Threat Research"


def _is_staff_or_threat_researcher(user) -> bool:
    """Return True if the user is active and is staff or in the Threat Research group."""
    if not user.is_active:
        return False
    if user.is_staff:
        return True
    return user.groups.filter(name=THREAT_RESEARCH_GROUP).exists()


def threat_research_required(view_func: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """Decorator that restricts access to staff and Threat Research group members.

    - Unauthenticated users are redirected to LOGIN_URL.
    - Authenticated users without permission are redirected to the dashboard
      with an error message.
    """

    @functools.wraps(view_func)
    def _wrapped(request: HttpRequest, *args, **kwargs) -> HttpResponse:
        if not request.user.is_authenticated:
            logger.debug("threat_research_required: unauthenticated user, redirecting to login")
            return redirect(settings.LOGIN_URL)

        if _is_staff_or_threat_researcher(request.user):
            return view_func(request, *args, **kwargs)

        logger.warning(
            "threat_research_required: user %s denied access to %s",
            request.user.pk,
            request.path,
        )
        messages.error(request, "You do not have permission to access this page.")
        return redirect("mission_control:dashboard")

    return _wrapped
