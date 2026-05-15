"""Access control utilities for Shifter views and CMS authoring services."""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

from shared.constants import USER_CANNOT_BE_NONE, USER_MUST_BE_SAVED

logger = logging.getLogger(__name__)

THREAT_RESEARCH_GROUP = "Threat Research"
CTF_ORGANIZER_GROUP = "CTF Organizer"
CTF_PARTICIPANT_GROUP = "CTF Participant"


def is_ctf_organizer(user) -> bool:
    """Return True if the user is in the CTF Organizer group."""
    if not user.is_active:
        return False
    return user.groups.filter(name=CTF_ORGANIZER_GROUP).exists()


def is_ctf_participant(user) -> bool:
    """Return True if the user is in the CTF Participant group."""
    if not user.is_active:
        return False
    return user.groups.filter(name=CTF_PARTICIPANT_GROUP).exists()


def is_ctf_participant_only(user) -> bool:
    """Return True if the user has no platform role that grants Launch Range.

    CTF roles (Participant, Organizer) do NOT grant Launch Range access.
    Only staff, superuser, or Threat Research group grants it.

    A user is "CTF only" when they:
    - ARE in a CTF group (Participant or Organizer)
    - Are NOT staff or superuser
    - Are NOT in Threat Research group
    """
    if not user.is_active:
        return False
    if user.is_staff or user.is_superuser:
        return False
    user_groups = set(user.groups.values_list("name", flat=True))
    has_ctf_role = bool(user_groups & {CTF_PARTICIPANT_GROUP, CTF_ORGANIZER_GROUP})
    if not has_ctf_role:
        return False
    return THREAT_RESEARCH_GROUP not in user_groups


def can_edit_cms_authoring(user) -> bool:
    """Return True if the user may use the CMS authoring surfaces.

    Canonical policy for the experiment and scenario editor: an active user
    who is either staff or a member of the ``Threat Research`` group. This
    predicate is the single source of truth for view decorators, service-layer
    gates, and template context — service-layer authorization MUST consume
    this rather than re-implementing the group check locally.
    """
    if not user.is_active:
        return False
    if user.is_staff:
        return True
    return user.groups.filter(name=THREAT_RESEARCH_GROUP).exists()


def validate_cms_authoring_user(user, func_name: str) -> None:
    """Validate user shape and CMS authoring authorization in one step.

    Combines the structural user-presence checks (None / instance / saved)
    used across CMS service modules with the canonical authorization
    predicate so experiment- and scenario-editor service entrypoints share a
    single validator. The wrapper exists so every CMS authoring service
    module collapses to a one-line delegation, eliminating the historical
    near-duplicate ``_validate_user`` bodies.
    """
    if user is None:
        logger.error("%s called with None user", func_name)
        raise TypeError(USER_CANNOT_BE_NONE)
    if not hasattr(user, "id"):
        logger.error(
            "%s called with invalid user type: %s",
            func_name,
            type(user).__name__,
        )
        raise TypeError(f"user must be a User instance, got {type(user).__name__}")
    if user.id is None:
        logger.error("%s called with unsaved user (id=None)", func_name)
        raise ValueError(USER_MUST_BE_SAVED)
    if not can_edit_cms_authoring(user):
        logger.warning("%s denied: user_id=%s not staff or Threat Research", func_name, user.id)
        raise PermissionDenied("Active staff or Threat Research group membership is required")


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

        if can_edit_cms_authoring(request.user):
            return view_func(request, *args, **kwargs)

        logger.warning(
            "threat_research_required: user %s denied access to %s",
            request.user.pk,
            request.path,
        )
        messages.error(request, "You do not have permission to access this page.")
        return redirect("mission_control:dashboard")

    return _wrapped
