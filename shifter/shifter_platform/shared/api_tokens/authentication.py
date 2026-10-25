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
from shared.api_tokens.policy import require_personal_token_grant
from shared.api_tokens.scopes import credential_ceiling
from shared.credentials import CredentialContext, verify_service_credential
from shared.principal_port import principal_for_user

if TYPE_CHECKING:
    from rest_framework.request import Request

_DEFAULT_COALESCE_SECONDS = 300


def _invalid_token_message() -> str:
    """Return the intentionally generic bearer authentication failure."""
    return "Invalid or expired API token"


class ApiTokenAuthentication(authentication.BaseAuthentication):
    """Bearer-token authentication for the platform API."""

    keyword = "Bearer"

    def _parse_bearer_token(self, request: Request) -> str | None:
        """Return the raw bearer credential, or None when none was supplied.

        Once a bearer credential is present we own the request and fail closed on
        any malformed header rather than falling through to session auth.
        """
        raw_header = authentication.get_authorization_header(request)
        if len(raw_header) > 16384:
            raise exceptions.AuthenticationFailed(_invalid_token_message())
        header = raw_header.split()

        if not header or header[0].lower() != self.keyword.lower().encode():
            return None

        if len(header) == 1:
            raise exceptions.AuthenticationFailed("Invalid token header. No credentials provided.")
        if len(header) > 2:
            raise exceptions.AuthenticationFailed("Invalid token header. Token string should not contain spaces.")

        try:
            return header[1].decode()
        except UnicodeError as exc:
            raise exceptions.AuthenticationFailed("Invalid token header. Token string is malformed.") from exc

    def _reject_ineligible_owner(self, token: ApiToken) -> None:
        """Fail closed for a token whose owner may not authenticate.

        A CTF-account owner's token is revoked on sight; a token whose owner is
        missing, inactive, or soft-deleted is rejected as defense in depth for the
        account lifecycle (PLAT-236, #1943) on top of the transition's revocation.
        """
        owner = token.created_by
        if token.created_by_id and getattr(getattr(owner, "profile", None), "is_ctf_account", False):
            token.revoke()
            raise exceptions.AuthenticationFailed(_invalid_token_message())
        if not token.has_eligible_owner:
            raise exceptions.AuthenticationFailed(_invalid_token_message())

    def authenticate(self, request: Request) -> tuple[None, ApiToken | CredentialContext] | None:
        request.credential_context = None
        raw_token = self._parse_bearer_token(request)
        if raw_token is None:
            # No bearer credential supplied -> let session auth try.
            return None

        if not raw_token.startswith(TOKEN_PREFIX):
            try:
                if raw_token.count(".") != 2:
                    raise ValueError("Unknown credential shape")
                credential = verify_service_credential(raw_token)
            except Exception:
                raise exceptions.AuthenticationFailed(_invalid_token_message()) from None
            request.credential_context = credential
            return None, credential

        token = ApiToken.authenticate(raw_token) if raw_token.startswith(TOKEN_PREFIX) else None
        if token is None:
            record_token_event(
                TokenEvent.AUTH_FAILED,
                request=request,
                context=_invalid_token_message(),
            )
            raise exceptions.AuthenticationFailed(_invalid_token_message())

        self._reject_ineligible_owner(token)
        try:
            owner = token.created_by
            if owner is None:
                raise ValueError("Credential owner unavailable")
            principal = principal_for_user(owner)
            if token.principal_uuid != principal.uuid:
                raise ValueError("Credential owner mismatch")
            require_personal_token_grant(principal)
            request.credential_context = CredentialContext(
                principal=principal,
                kind="personal",
                credential_uuid=token.credential_uuid,
                ceiling=credential_ceiling(token.scopes, target=token.target),
                scopes=frozenset(token.scopes),
            )
        except Exception:
            raise exceptions.AuthenticationFailed(_invalid_token_message()) from None

        coalesce_seconds = getattr(settings, "API_TOKEN_LAST_USED_COALESCE_SECONDS", _DEFAULT_COALESCE_SECONDS)
        token.touch_last_used(coalesce_seconds=coalesce_seconds)

        # (user, auth): user is None for token auth; the token is request.auth.
        return (None, token)

    def authenticate_header(self, request: Request) -> str:
        """Return the WWW-Authenticate header value, so missing/failed auth is 401."""
        return self.keyword
