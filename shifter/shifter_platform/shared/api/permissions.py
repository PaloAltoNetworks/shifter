"""Shared DRF permissions for platform API infrastructure endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rest_framework import permissions

from shared.api_tokens.models import ApiToken

if TYPE_CHECKING:
    from rest_framework.request import Request
    from rest_framework.views import APIView


class IsAuthenticatedSessionOrApiToken(permissions.BasePermission):
    """Allow authenticated browser sessions or valid platform API tokens."""

    message = "Authentication credentials were not provided."

    def has_permission(self, request: Request, view: APIView) -> bool:
        if isinstance(getattr(request, "auth", None), ApiToken):
            return True
        user = getattr(request, "user", None)
        return bool(user and user.is_authenticated)


class IsStaffSession(permissions.BasePermission):
    """Session-authenticated staff/superuser only; platform token principals rejected.

    A platform API token carries no Django user and no management scope, so
    endpoints authorized by this class are session-only (ADR-029). Used by the
    Administer user-administration surface (#1373).
    """

    message = "This action requires a staff session."

    def has_permission(self, request: Request, view: APIView) -> bool:
        if isinstance(getattr(request, "auth", None), ApiToken):
            return False
        user = getattr(request, "user", None)
        return bool(user and user.is_authenticated and (user.is_staff or user.is_superuser))


class RequireModelPermission(permissions.BasePermission):
    """Require specific Django model permission codenames on the request user.

    ``is_staff`` alone is never authorization; each endpoint declares the exact
    codenames it needs (e.g. ``auth.view_user`` / ``auth.change_user``).
    Superusers implicitly pass Django's ``has_perm``; a staff user lacking the
    codename is denied. Build concrete classes with :func:`require_model_permission`.
    """

    required_perms: tuple[str, ...] = ()

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = getattr(request, "user", None)
        if not (user and user.is_authenticated):
            return False
        return all(user.has_perm(perm) for perm in self.required_perms)


def require_model_permission(*perms: str) -> type[permissions.BasePermission]:
    """Return a :class:`RequireModelPermission` subclass requiring all of ``perms``."""
    return type("RequireModelPermission", (RequireModelPermission,), {"required_perms": tuple(perms)})
