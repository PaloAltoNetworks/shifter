"""OpenAPI schema extensions for shared platform API integrations."""

from __future__ import annotations

import logging
from typing import Any

from drf_spectacular.extensions import OpenApiAuthenticationExtension
from drf_spectacular.openapi import AutoSchema
from rest_framework import serializers

logger = logging.getLogger(__name__)

# Apps whose ``/api/v1/`` surface is not yet part of the published contract
# (#1329). CTF (``ctf.*``) was excluded until its SPA consumer (#1372) landed;
# its routes are now typed DRF views (ctf.api.organizer_views / participant_views)
# and join the published contract additively, so the tuple is empty. The hook
# stays wired so a future app can be staged the same way. Exclusion here affects
# only schema generation — runtime routing, authentication, and behavior are
# unchanged, so no existing consumer is broken.
UNPUBLISHED_VIEW_MODULE_PREFIXES: tuple[str, ...] = ()

# drf-spectacular endpoint tuple: (path, path_regex, method, callback).
Endpoint = tuple[str, str, str, Any]


class ApiTokenAuthenticationScheme(OpenApiAuthenticationExtension):
    """Document PLAT-102 bearer tokens in generated OpenAPI schemas."""

    target_class = "shared.api_tokens.authentication.ApiTokenAuthentication"
    name = "ApiTokenAuth"

    def get_security_definition(self, auto_schema: Any) -> dict[str, str]:
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "shf",
            "description": "Platform API token with scopes from shared.api_tokens.scopes.",
        }


def exclude_unpublished_endpoints(endpoints: list[Endpoint], **kwargs: Any) -> list[Endpoint]:
    """drf-spectacular ``PREPROCESSING_HOOK``: drop endpoints for apps not yet
    part of the published ``/api/v1/`` contract.

    An endpoint is excluded when its view class lives in an app listed in
    :data:`UNPUBLISHED_VIEW_MODULE_PREFIXES`. This keeps the committed artifact
    scoped to the SPA-facing surface without altering runtime routing.
    """
    published: list[Endpoint] = []
    for endpoint in endpoints:
        _path, _path_regex, _method, callback = endpoint
        view_cls = getattr(callback, "cls", None)
        module = getattr(view_cls, "__module__", "") or ""
        if module.startswith(UNPUBLISHED_VIEW_MODULE_PREFIXES):
            continue
        published.append(endpoint)
    return published


class ApiErrorBodySerializer(serializers.Serializer):
    """Schema-only description of the ``shared.api.errors`` envelope body."""

    code = serializers.CharField(help_text="Stable machine-readable error code.")
    message = serializers.CharField(help_text="Safe, user-facing error message.")
    details = serializers.JSONField(
        required=False,
        help_text="Optional structured field-level detail (present on validation errors).",
    )
    request_id = serializers.CharField(
        required=False,
        help_text="Correlation id echoed from the X-Request-ID request header, when present.",
    )


class ApiErrorSerializer(serializers.Serializer):
    """Schema-only component for the canonical platform API error envelope.

    Mirrors :func:`shared.api.errors.api_exception_handler` /
    :func:`shared.api.errors.api_error_response` output. It describes the wire
    contract; it never runs at request time.
    """

    error = ApiErrorBodySerializer()


class LegacyErrorSerializer(serializers.Serializer):
    """Schema-only description of the flat ``{"error": "<message>"}`` body some
    legacy Mission Control endpoints return (e.g. Guacamole bootstrap 503/404).

    This is NOT the canonical :class:`ApiErrorSerializer` envelope. It exists so
    the contract describes those endpoints' real wire shape truthfully rather
    than pretending they use the structured envelope. New endpoints must use the
    canonical envelope; this documents existing behavior, it does not endorse it.
    """

    error = serializers.CharField(help_text="Human-readable error message.")


_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Error responses guaranteed by the shared DRF exception handler for EVERY
# authenticated operation, independent of the view body: authentication and
# authorization run before the view and always render the shared envelope. These
# are always truthful. Body-dependent statuses (400/404/410 and their shapes)
# vary per endpoint — some legacy views return non-envelope errors — so they are
# declared per-view where they apply rather than injected globally; the contract
# never over-claims a response an endpoint does not actually return.
_GUARANTEED_ERROR_DESCRIPTIONS: dict[str, str] = {
    "401": "Authentication failed.",
    "403": "Permission denied.",
}


class PlatformAutoSchema(AutoSchema):
    """Project AutoSchema: publish per-operation token scopes and the shared
    error envelope so the contract is complete without reading Python source.

    - ``x-required-scopes``: the exact application scopes a bearer token needs,
      read from the ``require_scope`` permission on the view (never inferred
      from the path). Session-authenticated browser requests do not use scopes.
    - Standard error responses referencing :class:`ApiErrorSerializer`.
    """

    def get_operation(
        self,
        path: str,
        path_regex: str,
        path_prefix: str,
        method: str,
        registry: Any,
    ) -> dict[str, Any] | None:
        operation = super().get_operation(path, path_regex, path_prefix, method, registry)
        if operation is None:
            return None
        scopes = self._required_scopes(method)
        if scopes:
            operation["x-required-scopes"] = scopes
        self._add_error_responses(operation)
        return operation

    def _required_scopes(self, method: str) -> list[str]:
        """Return the token scopes required for ``method`` on the current view.

        Resolves permissions through the view's ``get_permissions()`` so views
        that vary scopes per method (e.g. read on GET, write on PATCH via
        ``get_permissions``) are reported truthfully, not just those with a
        static ``permission_classes`` list.
        """
        attr = "required_read_scope" if method.upper() in _SAFE_METHODS else "required_write_scope"
        collected: list[str] = []
        for permission in self._resolved_permissions():
            scope = getattr(permission, attr, None)
            if isinstance(scope, str) and scope and scope not in collected:
                collected.append(scope)
        return collected

    def _resolved_permissions(self) -> list[Any]:
        """Return permission instances for the operation being documented.

        ``get_permissions()`` honors per-method permission resolution and, for
        the static case, simply instantiates ``permission_classes``. drf-spectacular
        sets the view's request to the current method before schema generation,
        so this yields the operation-accurate permission set.
        """
        get_permissions = getattr(self.view, "get_permissions", None)
        if callable(get_permissions):
            try:
                return list(get_permissions())
            except Exception:
                # Schema generation must not crash on a view's dynamic permissions.
                logger.debug(
                    "get_permissions() failed during schema generation for %s; using static permission_classes",
                    type(self.view).__name__,
                    exc_info=True,
                )
        return [
            permission() if isinstance(permission, type) else permission
            for permission in getattr(self.view, "permission_classes", [])
        ]

    def _add_error_responses(self, operation: dict[str, Any]) -> None:
        """Attach the shared error envelope to the operation's guaranteed failures.

        Only statuses the DRF exception handler always produces (401/403, and 429
        when the view is throttled) are injected, so every published error
        response is truthful regardless of the view's body.
        """
        responses: dict[str, Any] = operation.setdefault("responses", {})
        error_ref = self.resolve_serializer(ApiErrorSerializer, "response").ref
        descriptions = dict(_GUARANTEED_ERROR_DESCRIPTIONS)
        if getattr(self.view, "throttle_classes", None):
            descriptions["429"] = "Request was throttled."
        for code, description in descriptions.items():
            responses.setdefault(
                code,
                {"content": {"application/json": {"schema": error_ref}}, "description": description},
            )
