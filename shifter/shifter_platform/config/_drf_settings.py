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
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
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
}

__all__ = ["REST_FRAMEWORK", "SPECTACULAR_SETTINGS"]
