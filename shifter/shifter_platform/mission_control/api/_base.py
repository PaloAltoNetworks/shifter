"""Shared helpers for Mission Control DRF views."""

from __future__ import annotations

from typing import Any, cast

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import HttpRequest
from rest_framework import permissions, serializers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from mission_control.api.permissions import HasMissionControlActor, mission_control_actor_user
from shared.api.errors import api_error_response
from shared.api.permissions import IsAuthenticatedSessionOrApiToken
from shared.api_tokens import scopes
from shared.api_tokens.permissions import require_scope

PermissionClass = type[permissions.BasePermission]
ValidationResult = tuple[dict[str, Any], None] | tuple[None, Response]


def _scope_permission(read_scope: str, write_scope: str | None = None) -> PermissionClass:
    """Build a DRF API-token permission for one Mission Control scope pair."""
    return require_scope(read_scope, write_scope or read_scope)


def _range_read_permission() -> PermissionClass:
    """Build the Mission Control range-read scope permission."""
    return require_scope(scopes.MISSION_CONTROL_RANGE_READ, scopes.MISSION_CONTROL_RANGE_READ)


def _range_write_permission() -> PermissionClass:
    """Build the Mission Control range-write scope permission."""
    return require_scope(scopes.MISSION_CONTROL_RANGE_READ, scopes.MISSION_CONTROL_RANGE_WRITE)


def _upload_write_permission() -> PermissionClass:
    """Build the Mission Control upload-write scope permission."""
    return _scope_permission(scopes.MISSION_CONTROL_UPLOAD_WRITE)


def _guacamole_read_permission() -> PermissionClass:
    """Build the Mission Control Guacamole-read scope permission."""
    return _scope_permission(scopes.MISSION_CONTROL_GUACAMOLE_READ)


def _ngfw_read_permission() -> PermissionClass:
    """Build the Mission Control NGFW-read scope permission."""
    return _scope_permission(scopes.MISSION_CONTROL_NGFW_READ)


def _ngfw_write_permission() -> PermissionClass:
    """Build the Mission Control NGFW-write scope permission."""
    return _scope_permission(scopes.MISSION_CONTROL_NGFW_READ, scopes.MISSION_CONTROL_NGFW_WRITE)


def _credentials_write_permission() -> PermissionClass:
    """Build the Mission Control credential-write scope permission."""
    return _scope_permission(scopes.MISSION_CONTROL_CREDENTIALS_WRITE)


def _vpn_profile_read_permission() -> PermissionClass:
    """Build the narrow Mission Control private-key delivery permission."""
    return _scope_permission(scopes.MISSION_CONTROL_VPN_PROFILE_READ)


class MissionControlAPIView(APIView):
    """Base class for authenticated Mission Control DRF endpoints."""

    permission_classes = [IsAuthenticatedSessionOrApiToken, HasMissionControlActor, _range_write_permission()]

    def actor_user(self) -> User:
        """Return the user whose Mission Control resources this request acts on."""
        user = mission_control_actor_user(self.request)
        if user is None:
            raise DjangoPermissionDenied("Authenticated user unavailable")
        return user

    def invalid(self, serializer: serializers.Serializer) -> Response:
        """Return validation errors in the canonical API error format."""
        return api_error_response(
            code="invalid",
            message="Invalid request",
            status_code=status.HTTP_400_BAD_REQUEST,
            details=serializer.errors,
            request=self.request,
        )

    def bad_request(self, message: str) -> Response:
        """Return a 400 response in the canonical API error format."""
        return api_error_response(
            code="bad_request",
            message=message,
            status_code=status.HTTP_400_BAD_REQUEST,
            request=self.request,
        )

    def not_found(self, message: str) -> Response:
        """Return a 404 response in the canonical API error format."""
        return api_error_response(
            code="not_found",
            message=message,
            status_code=status.HTTP_404_NOT_FOUND,
            request=self.request,
        )

    def error_response(self, *, code: str, message: str, status_code: int) -> Response:
        """Return a structured error in the canonical API error format."""
        return api_error_response(code=code, message=message, status_code=status_code, request=self.request)


class MissionControlReadAPIView(MissionControlAPIView):
    """Read-only Mission Control endpoint."""

    permission_classes = [IsAuthenticatedSessionOrApiToken, HasMissionControlActor, _range_read_permission()]


def _raw_request(drf_request: Request) -> HttpRequest:
    """Return the underlying Django request while preserving DRF auth state."""
    raw = getattr(drf_request, "_request", drf_request)
    raw.auth = getattr(drf_request, "auth", None)
    return cast(HttpRequest, raw)


def _validated(
    view: MissionControlAPIView,
    serializer_class: type[serializers.Serializer],
    data: object,
) -> ValidationResult:
    """Validate request data with a DRF serializer and return data or response."""
    serializer = serializer_class(data=data)
    if not serializer.is_valid():
        return None, view.invalid(serializer)
    return cast(dict[str, Any], serializer.validated_data), None
