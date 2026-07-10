"""Shared DRF boundary helpers for the CTF API."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from importlib import import_module
from typing import Any, ClassVar, cast

from django.contrib.auth.models import AnonymousUser
from django.http import HttpRequest, HttpResponse, JsonResponse
from rest_framework import permissions, serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ctf.bridges import get_user_role
from ctf.services.participant import is_active_participant
from shared.api.errors import api_error_response
from shared.api.permissions import IsAuthenticatedSessionOrApiToken
from shared.api_tokens.models import ApiToken
from shared.api_tokens.scopes import has_scope

PermissionClass = type[permissions.BasePermission]
LegacyView = Callable[..., HttpResponse]


class JSONBodySerializer(serializers.BaseSerializer[dict[str, Any]]):
    """Validate that a JSON request body is an object while preserving keys."""

    def to_internal_value(self, data: object) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise serializers.ValidationError("Request body must be a JSON object")
        return dict(data)

    def to_representation(self, instance: dict[str, Any]) -> dict[str, Any]:
        return instance


def ctf_actor_user(request: Request) -> Any | None:
    """Return the active user represented by a session or platform API token."""
    auth = getattr(request, "auth", None)
    user = auth.created_by if isinstance(auth, ApiToken) else getattr(request, "user", None)
    if isinstance(user, AnonymousUser) or not getattr(user, "is_authenticated", False):
        return None
    return user if getattr(user, "is_active", False) else None


class HasActiveCTFActor(permissions.BasePermission):
    """Require a session user or an API token owned by an active user."""

    message = "API token is not associated with an active user."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return ctf_actor_user(request) is not None


class HasCTFOrganizer(permissions.BasePermission):
    """Require the resolved actor to be a CTF organizer."""

    message = "Forbidden"

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = ctf_actor_user(request)
        return bool(user and get_user_role(user).is_ctf_organizer)


class HasCTFParticipant(permissions.BasePermission):
    """Require the resolved actor to be an active CTF participant."""

    message = "Forbidden"

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = ctf_actor_user(request)
        return bool(user and is_active_participant(user))


class HasCTFRole(permissions.BasePermission):
    """Require the resolved actor to have any CTF role."""

    message = "Forbidden"

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = ctf_actor_user(request)
        if user is None:
            return False
        role = get_user_role(user)
        return role.is_ctf_organizer or role.is_ctf_participant


class HasCTFEndpointScope(permissions.BasePermission):
    """Admit API-token requests only when they carry one declared CTF scope."""

    message = "API token is missing the required scope."

    def has_permission(self, request: Request, view: APIView) -> bool:
        auth = getattr(request, "auth", None)
        if not isinstance(auth, ApiToken):
            return True
        required = _required_scopes_for_method(request.method, view)
        return any(has_scope(auth.scopes, scope) for scope in required)


CTF_AUTH_PERMISSIONS: list[PermissionClass] = [
    IsAuthenticatedSessionOrApiToken,
    HasActiveCTFActor,
    HasCTFEndpointScope,
]

CTF_ORGANIZER_PERMISSIONS: list[PermissionClass] = [*CTF_AUTH_PERMISSIONS, HasCTFOrganizer]
CTF_PARTICIPANT_PERMISSIONS: list[PermissionClass] = [*CTF_AUTH_PERMISSIONS, HasCTFParticipant]
CTF_ROLE_PERMISSIONS: list[PermissionClass] = [*CTF_AUTH_PERMISSIONS, HasCTFRole]


class CTFLegacyAPIView(APIView):
    """DRF wrapper around the existing CTF service-backed JSON view callables."""

    versioning_class = None
    legacy_view: ClassVar[LegacyView | None] = None
    legacy_view_path: ClassVar[str] = ""
    required_read_scopes: ClassVar[tuple[str, ...]] = ()
    required_write_scopes: ClassVar[tuple[str, ...]] = ()
    json_body_methods: ClassVar[frozenset[str]] = frozenset({"POST", "PUT", "PATCH", "DELETE"})

    def get(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse | Response:
        return self._dispatch_legacy(request, *args, **kwargs)

    def post(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse | Response:
        return self._dispatch_legacy(request, *args, **kwargs)

    def put(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse | Response:
        return self._dispatch_legacy(request, *args, **kwargs)

    def delete(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse | Response:
        return self._dispatch_legacy(request, *args, **kwargs)

    def _dispatch_legacy(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse | Response:
        raw_request = self._prepare_raw_request(request)
        response = self._legacy_view()(raw_request, *args, **kwargs)
        return _canonical_error_response(request, response) or response

    def _prepare_raw_request(self, request: Request) -> HttpRequest:
        raw_request = cast(HttpRequest, getattr(request, "_request", request))
        actor = ctf_actor_user(request)
        if actor is not None:
            raw_request.user = actor
        cast(Any, raw_request).auth = getattr(request, "auth", None)
        if _should_validate_json_body(raw_request) and raw_request.method in self.json_body_methods:
            body_empty = _request_body_empty(raw_request)
            serializer = JSONBodySerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            raw_request._ctf_drf_body_data = serializer.validated_data  # type: ignore[attr-defined]
            raw_request._ctf_drf_body_empty = body_empty  # type: ignore[attr-defined]
        return raw_request

    def _legacy_view(self) -> LegacyView:
        if self.legacy_view is not None:
            return self.legacy_view
        module_path, function_name = self.legacy_view_path.rsplit(".", 1)
        return cast(LegacyView, getattr(import_module(module_path), function_name))


def legacy_api_view(
    name: str,
    legacy_view_path: str,
    *,
    permission_classes: Iterable[PermissionClass],
    read_scopes: tuple[str, ...] = (),
    write_scopes: tuple[str, ...] = (),
) -> Callable[..., Any]:
    """Create a DRF view callable that delegates to a legacy CTF JSON endpoint."""
    view_class = cast(
        type[CTFLegacyAPIView],
        type(
            name,
            (CTFLegacyAPIView,),
            {
                "__module__": __name__,
                "__doc__": f"DRF wrapper for {legacy_view_path}.",
                "legacy_view_path": legacy_view_path,
                "permission_classes": list(permission_classes),
                "required_read_scopes": read_scopes,
                "required_write_scopes": write_scopes,
            },
        ),
    )
    return cast(Callable[..., Any], view_class.as_view())


def _required_scopes_for_method(method: str, view: APIView) -> Iterable[str]:
    """Return the declared CTF token scopes for the incoming HTTP method."""
    scopes = getattr(view, "required_read_scopes", ()) if method in permissions.SAFE_METHODS else ()
    if method not in permissions.SAFE_METHODS:
        scopes = getattr(view, "required_write_scopes", ())
    return tuple(scopes)


def _should_validate_json_body(request: HttpRequest) -> bool:
    """Return true when the request content type should be parsed as JSON."""
    content_type = request.META.get("CONTENT_TYPE", "")
    return "json" in content_type.lower()


def _request_body_empty(request: HttpRequest) -> bool:
    """Return true when the request declares an empty body."""
    try:
        return int(request.META.get("CONTENT_LENGTH") or 0) == 0
    except ValueError:
        return False


def _canonical_error_response(request: Request, response: HttpResponse) -> Response | None:
    """Convert canonical CTF legacy flat-error JSON to the shared API envelope."""
    message = _legacy_error_message(request, response)
    if message is None:
        return None

    converted = api_error_response(
        code=_error_code_for_status(response.status_code),
        message=message,
        status_code=response.status_code,
        request=request,
    )
    for header in ("Retry-After", "Location"):
        if response.has_header(header):
            converted[header] = response[header]
    return converted


def _legacy_error_message(request: Request, response: HttpResponse) -> str | None:
    """Extract a flat legacy error message when a response is eligible."""
    message = None
    if request.path.startswith("/api/v1/ctf/") and response.status_code >= 400 and isinstance(response, JsonResponse):
        try:
            payload = json.loads(response.content.decode(response.charset or "utf-8"))
        except ValueError:
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("error"), str):
            message = cast(str, payload["error"])
    return message


def _error_code_for_status(status_code: int) -> str:
    """Map legacy CTF HTTP statuses onto the shared API error-code vocabulary."""
    return {
        400: "bad_request",
        403: "permission_denied",
        404: "not_found",
        429: "throttled",
    }.get(status_code, "ctf_error")
