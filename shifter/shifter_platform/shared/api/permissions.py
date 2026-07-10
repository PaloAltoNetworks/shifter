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
