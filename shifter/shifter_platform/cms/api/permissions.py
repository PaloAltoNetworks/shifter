"""CMS DRF permissions and actor resolution."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from django.contrib.auth.models import AnonymousUser, User
from rest_framework import permissions

from shared.api.permissions import IsAuthenticatedSessionOrApiToken
from shared.api_tokens import scopes
from shared.api_tokens.models import ApiToken
from shared.api_tokens.permissions import require_scope
from shared.auth import can_edit_cms_authoring

if TYPE_CHECKING:
    from rest_framework.request import Request
    from rest_framework.views import APIView

PermissionClass = type[permissions.BasePermission]


def cms_actor_user(request: Request) -> User | None:
    """Return the session user or API-token owner for CMS authoring checks."""
    auth = getattr(request, "auth", None)
    user = auth.created_by if isinstance(auth, ApiToken) else getattr(request, "user", None)
    if user is None or isinstance(user, AnonymousUser):
        return None
    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return None
    return cast(User, user)


class HasCMSAuthoringActor(permissions.BasePermission):
    """Require the resolved actor to hold CMS authoring privileges."""

    message = "Forbidden"

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = cms_actor_user(request)
        return bool(user and can_edit_cms_authoring(user))


def _cms_read_scope_permission() -> PermissionClass:
    """Build the CMS authoring read-scope permission."""
    return require_scope(scopes.CMS_AUTHORING_READ, scopes.CMS_AUTHORING_READ)


def _cms_write_scope_permission() -> PermissionClass:
    """Build the CMS authoring write-scope permission."""
    return require_scope(scopes.CMS_AUTHORING_READ, scopes.CMS_AUTHORING_WRITE)


CMS_READ_PERMISSIONS: list[PermissionClass] = [
    IsAuthenticatedSessionOrApiToken,
    HasCMSAuthoringActor,
    _cms_read_scope_permission(),
]
CMS_WRITE_PERMISSIONS: list[PermissionClass] = [
    IsAuthenticatedSessionOrApiToken,
    HasCMSAuthoringActor,
    _cms_write_scope_permission(),
]
