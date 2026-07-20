"""Django REST Framework and OpenAPI settings for the platform API."""

from __future__ import annotations

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        # Scoped bearer tokens first (PLAT-102; fails closed), then session.
        # Legacy app-local authenticators are declared only on their owner views.
        "shared.api_tokens.authentication.ApiTokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "EXCEPTION_HANDLER": "shared.api.errors.api_exception_handler",
    # Publishes per-operation token scopes (x-required-scopes) and the shared
    # error envelope so the contract is complete without reading source (#1329).
    "DEFAULT_SCHEMA_CLASS": "shared.api.schema.PlatformAutoSchema",
    "DEFAULT_VERSIONING_CLASS": "rest_framework.versioning.NamespaceVersioning",
    "ALLOWED_VERSIONS": ["v1"],
    "DEFAULT_VERSION": "v1",
    "DEFAULT_FILTER_BACKENDS": [
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Shifter Platform API",
    "DESCRIPTION": "Authenticated HTTP/JSON API for Shifter platform integrations.",
    "VERSION": "v1",
    "SCHEMA_PATH_PREFIX": r"/api/v[0-9]+",
    "SERVE_INCLUDE_SCHEMA": False,
    "SERVE_PERMISSIONS": ["shared.api.permissions.IsAuthenticatedSessionOrApiToken"],
    "SWAGGER_UI_DIST": "SIDECAR",
    "SWAGGER_UI_FAVICON_HREF": "SIDECAR",
    "REDOC_DIST": "SIDECAR",
    # Scope the published contract to the SPA-facing surface (#1329). Apps whose
    # SPA consumer has not landed (CTF, pending #1372) are dropped from schema
    # generation; runtime routing is unaffected. See shared.api.schema.
    "PREPROCESSING_HOOKS": ["shared.api.schema.exclude_unpublished_endpoints"],
    # Stable component names for enums that would otherwise collide. Both the
    # Risk Register ``status`` (risk_register.models.Status) and the Mission
    # Control range ``status`` (shared.enums.ResourceStatus) auto-name to
    # "StatusEnum"; without overrides drf-spectacular hash-suffixes BOTH
    # (StatusE68Enum / StatusD12Enum), churning the Risk Register type name and
    # producing unstable, hash-dependent TS types. Pin each to a stable name.
    "ENUM_NAME_OVERRIDES": {
        "StatusEnum": "risk_register.models.Status",
        "ResourceStatusEnum": "mission_control.api.serializers.RESOURCE_STATUS_VALUES",
    },
}

__all__ = ["REST_FRAMEWORK", "SPECTACULAR_SETTINGS"]
