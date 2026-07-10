"""DRF authentication for platform API tokens (PLAT-102).

Clients authenticate programmatically with ``Authorization: Bearer shf_...``.
Browser/SPA clients keep using session-cookie auth (DRF ``SessionAuthentication``
runs after this class). The two are wired as the platform DRF default in
``config.settings.REST_FRAMEWORK``.

Fail-closed contract (preflight guardrail): a *bad* bearer token raises
``AuthenticationFailed`` and never falls through to a session on the same
request; *no* bearer credential returns ``None`` so session auth can run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from rest_framework import authentication, exceptions

from shared.api_tokens.audit import TokenEvent, record_token_event
from shared.api_tokens.models import TOKEN_PREFIX, ApiToken

if TYPE_CHECKING:
    from rest_framework.request import Request

_DEFAULT_COALESCE_SECONDS = 300


class ApiTokenAuthentication(authentication.BaseAuthentication):
    """Bearer-token authentication for the platform API."""

    keyword = "Bearer"

    def authenticate(self, request: Request) -> tuple[None, ApiToken] | None:
        header = authentication.get_authorization_header(request).split()

        if not header or header[0].lower() != self.keyword.lower().encode():
            # No bearer credential supplied -> let session auth try.
            return None

        # A bearer credential WAS supplied: from here we own it and fail closed.
        if len(header) == 1:
            raise exceptions.AuthenticationFailed("Invalid token header. No credentials provided.")
        if len(header) > 2:
            raise exceptions.AuthenticationFailed("Invalid token header. Token string should not contain spaces.")

        try:
            raw_token = header[1].decode()
        except UnicodeError as exc:
            raise exceptions.AuthenticationFailed("Invalid token header. Token string is malformed.") from exc

        token = ApiToken.authenticate(raw_token) if raw_token.startswith(TOKEN_PREFIX) else None
        if token is None:
            record_token_event(
                TokenEvent.AUTH_FAILED,
                request=request,
                context="Invalid or expired API token",
            )
            raise exceptions.AuthenticationFailed("Invalid or expired API token")

        coalesce_seconds = getattr(settings, "API_TOKEN_LAST_USED_COALESCE_SECONDS", _DEFAULT_COALESCE_SECONDS)
        token.touch_last_used(coalesce_seconds=coalesce_seconds)

        # (user, auth): user is None for token auth; the token is request.auth.
        return (None, token)

    def authenticate_header(self, request: Request) -> str:
        """Return the WWW-Authenticate header value, so missing/failed auth is 401."""
        return self.keyword
