"""OIDC utilities for Cognito integration."""

import logging
import os
import re
from urllib.parse import urlencode

from mozilla_django_oidc.auth import OIDCAuthenticationBackend

from management.services import update_cognito_sub

logger = logging.getLogger(__name__)

# Django's UnicodeUsernameValidator pattern
DJANGO_USERNAME_PATTERN = re.compile(r"^[\w.@+-]+$")
DJANGO_USERNAME_MAX_LENGTH = 150


def generate_username(email: str) -> str:
    """Use email as username instead of default sha1 hash.

    mozilla-django-oidc defaults to base64(sha1(email)) for privacy
    (usernames are often public). For this internal tool, readable
    emails in admin/logs/queries are more useful than hash obfuscation.

    Raises:
        ValueError: If email exceeds Django's 150 char limit or contains
            characters not allowed in Django usernames. This indicates a
            mismatch between Cognito's allowed emails and Django's constraints
            that must be fixed at the source (Lambda allow-list).
    """
    if len(email) > DJANGO_USERNAME_MAX_LENGTH:
        logger.error(
            "OIDC username rejected: email exceeds %d chars (got %d): %s",
            DJANGO_USERNAME_MAX_LENGTH,
            len(email),
            email[:50] + "...",
        )
        raise ValueError(
            f"Email exceeds Django username limit of {DJANGO_USERNAME_MAX_LENGTH} characters. "
            "Fix the Cognito pre-signup Lambda allow-list."
        )

    if not DJANGO_USERNAME_PATTERN.match(email):
        logger.error(
            "OIDC username rejected: email contains invalid characters: %s",
            email,
        )
        raise ValueError(
            "Email contains characters not allowed in Django usernames. Fix the Cognito pre-signup Lambda allow-list."
        )

    return email


def provider_logout_url(request):
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
    """Custom OIDC backend that stores Cognito sub in UserProfile.

    The Cognito `sub` is the stable identifier for a user across tokens.
    We store it in UserProfile to enable MCP server lookups by sub
    (access tokens only contain sub, not email).
    """

    def create_user(self, claims):
        """Create user and populate cognito_sub from claims."""
        user = super().create_user(claims)
        self._update_cognito_sub(user, claims)
        return user

    def update_user(self, user, claims):
        """Update user and ensure cognito_sub is set."""
        user = super().update_user(user, claims)
        self._update_cognito_sub(user, claims)
        return user

    def _update_cognito_sub(self, user, claims):
        """Store Cognito sub in user's profile."""
        cognito_sub = claims.get("sub")
        if not cognito_sub:
            logger.warning("OIDC claims missing 'sub' for user %s", user.email)
            return

        update_cognito_sub(user, cognito_sub)
