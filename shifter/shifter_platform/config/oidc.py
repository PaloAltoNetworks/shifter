"""OIDC utilities for Cognito integration."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from mozilla_django_oidc.auth import OIDCAuthenticationBackend

from config.bootstrap_admin import apply_bootstrap_admin_flags
from config.cognito_groups import sync_cognito_groups_from_claims
from config.user_type_sync import sync_user_type
from management.services import update_cognito_sub
from risk_register.models import AuditLog
from risk_register.services import AuthPrincipal, audit_auth_event, get_client_ip

if TYPE_CHECKING:
    from django.contrib.auth.models import User
    from django.http import HttpRequest

logger = logging.getLogger(__name__)


def provider_logout_url(request: HttpRequest) -> str:
    """Return Cognito logout URL to clear the identity provider session.

    Called by mozilla-django-oidc's OIDCLogoutView when OIDC_OP_LOGOUT_URL_METHOD
    is configured. Redirects to Cognito's /logout endpoint which clears the
    Cognito session cookie, then redirects back to our logout_uri.

    In local dev (no OIDC env vars), returns "/" to skip Cognito and go home.

    See: https://docs.aws.amazon.com/cognito/latest/developerguide/logout-endpoint.html
    """
    auth_domain = os.environ.get("OIDC_AUTH_DOMAIN", "")
    client_id = os.environ.get("OIDC_RP_CLIENT_ID", "")

    if not auth_domain or not client_id:
        # Local dev - just redirect home, no Cognito to log out of
        return "/"

    # Build the post-logout redirect URL
    scheme = "https" if request.is_secure() else "http"
    host = request.get_host()
    logout_uri = f"{scheme}://{host}/"

    params = urlencode(
        {
            "client_id": client_id,
            "logout_uri": logout_uri,
        }
    )

    return f"{auth_domain}/logout?{params}"


class ShifterOIDCBackend(OIDCAuthenticationBackend):
    """Custom OIDC backend that stores Cognito sub and CTF user type in UserProfile.

    The Cognito `sub` is the stable identifier for a user across tokens.
    We store it in UserProfile to enable MCP server lookups by sub
    (access tokens only contain sub, not email).

    CTF-specific claims:
    - custom:user_type: Sets the user's role (standard, ctf_organizer, ctf_participant)
    - custom:ctf_event_id: Sets the active CTF event for participant users
    """

    def create_user(self, claims: dict[str, Any]) -> User:
        """Create user and populate cognito_sub and user_type from claims."""
        user = super().create_user(claims)
        apply_bootstrap_admin_flags(user, claims.get("email") or user.email)
        self._update_cognito_sub(user, claims)
        self._update_user_type(user, claims)
        sync_cognito_groups_from_claims(user, claims, getattr(self, "_request", None))

        # Audit log: new user created via OIDC
        cognito_sub = claims.get("sub", "")
        audit_auth_event(
            action=AuditLog.Action.CREATE,
            principal=AuthPrincipal(user_id=user.id, email=user.email, cognito_sub=cognito_sub),
            context="User created via OIDC first login",
        )

        return user

    def update_user(self, user: User, claims: dict[str, Any]) -> User:
        """Update user and ensure cognito_sub and user_type are set."""
        user = super().update_user(user, claims)
        apply_bootstrap_admin_flags(user, claims.get("email") or user.email)
        self._update_cognito_sub(user, claims)
        self._update_user_type(user, claims)
        sync_cognito_groups_from_claims(user, claims, getattr(self, "_request", None))
        return user

    def authenticate(self, request: HttpRequest | None, **kwargs: Any) -> User | None:
        """Authenticate and log the event."""
        # Stash the request so create_user / update_user (whose signatures are
        # fixed by mozilla-django-oidc and omit the request) can attribute the
        # user-type sync audit row to the request context (issue #937 SEC-5).
        self._request = request

        # Get request context for audit logging up front, so it is available on
        # both the return-None and the raising failure paths below.
        source_ip = None
        user_agent = ""
        if request:
            source_ip = get_client_ip(request)
            user_agent = request.META.get("HTTP_USER_AGENT", "")[:500]

        try:
            user = super().authenticate(request, **kwargs)
        except Exception as exc:
            # Token exchange, JWKS lookup, JWT/nonce/state validation, and
            # claims/user-creation errors raise here, before the ``user is None``
            # branch below. Audit them as a failed login with a *bounded* reason
            # — the exception type name only, never ``str(exc)``, which can carry
            # token endpoint URLs, response bodies, auth codes, or client ids —
            # then re-raise so mozilla-django-oidc's callback failure handling is
            # unchanged.
            audit_auth_event(
                action=AuditLog.Action.LOGIN_FAILED,
                source_ip=source_ip,
                user_agent=user_agent,
                context=f"OIDC authentication error: {type(exc).__name__}",
            )
            raise

        if user:
            # Successful authentication
            audit_auth_event(
                action=AuditLog.Action.LOGIN,
                principal=AuthPrincipal(
                    user_id=user.id,
                    email=user.email,
                    cognito_sub=(getattr(user, "userprofile", None) and getattr(user.userprofile, "cognito_sub", ""))
                    or "",
                ),
                source_ip=source_ip,
                user_agent=user_agent,
                context="OIDC callback login",
            )
        else:
            # Failed authentication - log without user details.
            # The backend returned None (no matching/valid user); we cannot get
            # the email here as auth failed.
            audit_auth_event(
                action=AuditLog.Action.LOGIN_FAILED,
                source_ip=source_ip,
                user_agent=user_agent,
                context="OIDC authentication failed: no_user",
            )

        return user

    def _update_cognito_sub(self, user: User, claims: dict[str, Any]) -> None:
        """Store Cognito sub in user's profile."""
        cognito_sub = claims.get("sub")
        if not cognito_sub:
            logger.warning("OIDC claims missing 'sub' for user %s", user.email)
            return

        update_cognito_sub(user, cognito_sub)

    def _update_user_type(self, user: User, claims: dict[str, Any]) -> None:
        """Sync CTF groups, profile user_type, and active CTF event from claims.

        Delegates to the shared, audited :func:`config.user_type_sync.sync_user_type`
        so OIDC, Identity Platform, and dev-login share one mapping and one
        fail-closed audit trail (issue #937 SEC-5).
        """
        sync_user_type(
            user,
            claims.get("custom:user_type"),
            source="oidc",
            request=getattr(self, "_request", None),
            ctf_event_id=claims.get("custom:ctf_event_id"),
        )
