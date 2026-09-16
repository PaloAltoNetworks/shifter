"""Mission Control DRF permissions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth.models import User
from rest_framework import permissions

from shared.api.principals import active_actor_user
from shared.auth import PARTICIPANT_ALLOWED_LIFECYCLE_VERBS, is_ctf_participant_only

if TYPE_CHECKING:
    from rest_framework.request import Request
    from rest_framework.views import APIView


def mission_control_actor_user(request: Request) -> User | None:
    """Return the user whose Mission Control resources this request acts on."""
    return active_actor_user(request)


class HasMissionControlActor(permissions.BasePermission):
    """Require a session user or an API token tied to a user."""

    message = "API token is not associated with an active user."

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = mission_control_actor_user(request)
        return bool(user and user.is_active)


def block_participant_lifecycle_permission(verb: str) -> type[permissions.BasePermission]:
    """Build a DRF permission equivalent of ``block_ctf_participant_only``."""

    class _BlockParticipantLifecycle(permissions.BasePermission):
        """Block participant-only users from disallowed lifecycle actions."""

        message = "Forbidden"

        def has_permission(self, request: Request, view: APIView) -> bool:
            user = mission_control_actor_user(request)
            return not (user and is_ctf_participant_only(user) and verb not in PARTICIPANT_ALLOWED_LIFECYCLE_VERBS)

    _BlockParticipantLifecycle.__name__ = f"BlockParticipantLifecycle[{verb}]"
    return _BlockParticipantLifecycle
