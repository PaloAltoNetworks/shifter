"""DRF scope permission for platform API tokens (PLAT-102).

``require_scope`` builds the central, reusable scope gate. It checks only the
*token* dimension: a request authenticated by an ``ApiToken`` must carry the
required scope (read scope for safe methods, write scope for unsafe ones).
Non-token (session) requests pass through here so that session authorization is
enforced by a sibling permission composed alongside this one. This keeps the
scope vocabulary and check in one place while leaving per-surface session
policy to each app.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rest_framework import permissions

from shared.api_tokens.models import ApiToken
from shared.api_tokens.scopes import has_scope

if TYPE_CHECKING:
    from rest_framework.request import Request
    from rest_framework.views import APIView


def require_scope(read_scope: str, write_scope: str | None = None) -> type[permissions.BasePermission]:
    """Build a permission requiring ``read_scope`` for safe methods and
    ``write_scope`` (defaults to ``read_scope``) for unsafe methods, for
    token-authenticated requests."""
    required_write = write_scope or read_scope

    class _RequireScope(permissions.BasePermission):
        """Permission that admits a token request only when it carries the scope."""

        message = "API token is missing the required scope."

        def has_permission(self, request: Request, view: APIView) -> bool:
            auth = getattr(request, "auth", None)
            if not isinstance(auth, ApiToken):
                # Not a token request; session authz is enforced elsewhere.
                return True
            required = read_scope if request.method in permissions.SAFE_METHODS else required_write
            return has_scope(auth.scopes, required)

    _RequireScope.__name__ = f"RequireScope[{read_scope}/{required_write}]"
    return _RequireScope
