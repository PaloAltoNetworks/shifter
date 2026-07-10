"""OpenAPI schema extensions for shared platform API integrations."""

from __future__ import annotations

from typing import Any

from drf_spectacular.extensions import OpenApiAuthenticationExtension


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
