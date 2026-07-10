"""Shared helpers for Mission Control DRF views."""

from __future__ import annotations

from typing import Any, cast

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import HttpRequest
from rest_framework import permissions, serializers, status
from rest_framework.exceptions import ParseError
from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied
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


class MissionControlAPIView(APIView):
    """Base class for authenticated Mission Control DRF endpoints."""

    permission_classes = [IsAuthenticatedSessionOrApiToken, HasMissionControlActor, _range_write_permission()]

    def determine_version(self, request: Request, *args: Any, **kwargs: Any) -> tuple[Any, Any]:
        """Force the compatibility namespace for legacy Mission Control routes."""
        if _is_legacy_request(request):
            return "v1", None
        return super().determine_version(request, *args, **kwargs)

    def handle_exception(self, exc: Exception) -> Response:
        """Preserve legacy flat error payloads for old Mission Control routes."""
        if _is_legacy_request(self.request):
            if isinstance(exc, ParseError):
                return Response({"error": "Invalid JSON"}, status=status.HTTP_400_BAD_REQUEST)
            if isinstance(exc, DRFPermissionDenied) and str(getattr(exc, "detail", "")) == "Forbidden":
                return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)
        response = super().handle_exception(exc)
        if _is_legacy_request(self.request) and response is not None:
            response.data = {"error": _legacy_error_message(response.data)}
        return response

    def actor_user(self) -> User:
        """Return the user whose Mission Control resources this request acts on."""
        user = mission_control_actor_user(self.request)
        if user is None:
            raise DjangoPermissionDenied("Authenticated user unavailable")
        return user

    def invalid(self, serializer: serializers.Serializer) -> Response:
        """Return validation errors in either legacy or canonical API format."""
        if _is_legacy_request(self.request):
            return Response(
                {"error": _first_serializer_error(serializer.errors)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return api_error_response(
            code="invalid",
            message="Invalid request",
            status_code=status.HTTP_400_BAD_REQUEST,
            details=serializer.errors,
            request=self.request,
        )

    def bad_request(self, message: str) -> Response:
        """Return a 400 response in either legacy or canonical API format."""
        if _is_legacy_request(self.request):
            return Response({"error": message}, status=status.HTTP_400_BAD_REQUEST)
        return api_error_response(
            code="bad_request",
            message=message,
            status_code=status.HTTP_400_BAD_REQUEST,
            request=self.request,
        )

    def not_found(self, message: str) -> Response:
        """Return a 404 response in either legacy or canonical API format."""
        if _is_legacy_request(self.request):
            return Response({"error": message}, status=status.HTTP_404_NOT_FOUND)
        return api_error_response(
            code="not_found",
            message=message,
            status_code=status.HTTP_404_NOT_FOUND,
            request=self.request,
        )

    def error_response(self, *, code: str, message: str, status_code: int) -> Response:
        """Return a structured error while retaining legacy flat responses."""
        if _is_legacy_request(self.request):
            return Response({"error": message}, status=status_code)
        return api_error_response(code=code, message=message, status_code=status_code, request=self.request)


class MissionControlReadAPIView(MissionControlAPIView):
    """Read-only Mission Control endpoint."""

    permission_classes = [IsAuthenticatedSessionOrApiToken, HasMissionControlActor, _range_read_permission()]


def _raw_request(drf_request: Request) -> HttpRequest:
    """Return the underlying Django request while preserving DRF auth state."""
    raw = getattr(drf_request, "_request", drf_request)
    raw.auth = getattr(drf_request, "auth", None)
    return cast(HttpRequest, raw)


def _is_legacy_request(request: object) -> bool:
    """Return whether a request is targeting the legacy URL namespace."""
    return str(getattr(request, "path", "")).startswith("/mission-control/")


def _first_serializer_error(errors: object) -> str:
    """Extract the first human-readable DRF serializer error."""
    message = "Invalid request"
    if isinstance(errors, dict):
        for value in errors.values():
            message = _first_serializer_error(value)
            break
    elif isinstance(errors, list) and errors:
        message = _first_serializer_error(errors[0])
    elif errors:
        message = str(errors)
    return message


def _legacy_error_message(data: object) -> str:
    """Extract a legacy-compatible error string from a DRF error payload."""
    message = "Request could not be processed"
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            value = error.get("message") or error.get("detail") or error.get("code")
            message = str(value or message)
        elif error is not None:
            message = str(error)
        elif data.get("detail") is not None:
            message = str(data["detail"])
    return message


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


def _is_empty_legacy_body(request: Request) -> bool:
    """Return whether a legacy request supplied no body at all."""
    if not _is_legacy_request(request):
        return False
    raw = getattr(request, "_request", request)
    return getattr(raw, "body", b"") == b""


def _guacamole_bootstrap_url_names(request: Request) -> dict[str, str]:
    """Return canonical Guacamole bootstrap route names for canonical API calls."""
    match = getattr(request, "resolver_match", None)
    if getattr(match, "namespace", "") == "v1:mission_control":
        return {
            "status_url_name": "v1:mission_control:guacamole-bootstrap-status",
            "open_url_name": "v1:mission_control:guacamole-bootstrap-open",
        }
    return {}
