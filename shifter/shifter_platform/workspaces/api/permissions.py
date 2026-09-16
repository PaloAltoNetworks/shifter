"""Authentication, actor, and exact-scope gates for workspace APIs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rest_framework import permissions

from shared.api.permissions import IsAuthenticatedSessionOrApiToken
from shared.api.principals import active_actor_user
from shared.api_tokens import scopes
from shared.api_tokens.permissions import require_scope

if TYPE_CHECKING:
    from rest_framework.request import Request
    from rest_framework.views import APIView

PermissionClass = type[permissions.BasePermission]


class HasActiveWorkspaceActor(permissions.BasePermission):
    """Require an active session user or active token owner."""

    message = "API token is not associated with an active user."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return active_actor_user(request) is not None


WORKSPACE_MEMBERSHIP_PERMISSIONS: list[PermissionClass] = [
    IsAuthenticatedSessionOrApiToken,
    HasActiveWorkspaceActor,
    require_scope(
        scopes.WORKSPACES_MEMBERSHIP_READ,
        scopes.WORKSPACES_MEMBERSHIP_WRITE,
    ),
]
