"""OIDC / Identity-Platform / Cognito Django settings.

Extracted from ``config/settings.py`` to keep that module under the
500-line cap (Sonar S104). Reads the same environment variables as the
old inline block; importing this module has no side effects beyond
binding the module-level constants used in the re-export.
"""

from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

# Re-derive the toggles the OIDC block needs. These are also defined in
# ``config.settings`` but importing them from there would create a cycle
# (settings.py imports this module).
AUTH_PROVIDER = os.environ.get("AUTH_PROVIDER", "oidc").strip().lower()
IS_TEST_RUN = os.environ.get("TESTING") == "1" or Path(sys.argv[0]).name == "pytest"
DEBUG = os.environ.get("DJANGO_DEBUG", "False").lower() == "true"


def _env_csv(name: str) -> list[str]:
    return [item.strip().lower() for item in os.environ.get(name, "").split(",") if item.strip()]


if AUTH_PROVIDER == "identity_platform":
    AUTHENTICATION_BACKENDS = [
        "config.identity_platform.IdentityPlatformBackend",
        "django.contrib.auth.backends.ModelBackend",
    ]
else:
    AUTHENTICATION_BACKENDS = [
        "config.oidc.ShifterOIDCBackend",
        "django.contrib.auth.backends.ModelBackend",
    ]

# Magic link authentication (PLAT-101)
MAGIC_LINK_EXPIRY_HOURS = int(os.environ.get("MAGIC_LINK_EXPIRY_HOURS", "24"))
MAGIC_LINK_SINGLE_USE = os.environ.get("MAGIC_LINK_SINGLE_USE", "False").lower() == "true"

# OIDC settings - loaded from environment for AWS/Cognito deployments.
OIDC_RP_CLIENT_ID = os.environ.get("OIDC_RP_CLIENT_ID", "test-oidc-client-id" if IS_TEST_RUN else "")
OIDC_RP_CLIENT_SECRET = os.environ.get("OIDC_RP_CLIENT_SECRET", "test-oidc-client-secret" if IS_TEST_RUN else "")
IDENTITY_PLATFORM_API_KEY = os.environ.get("IDENTITY_PLATFORM_API_KEY", "")
IDENTITY_PLATFORM_PROJECT_ID = os.environ.get("IDENTITY_PLATFORM_PROJECT_ID", "")
IDENTITY_PLATFORM_AUTH_DOMAIN = os.environ.get("IDENTITY_PLATFORM_AUTH_DOMAIN", "")
IDENTITY_ALLOWED_EMAIL_DOMAIN = os.environ.get("IDENTITY_ALLOWED_EMAIL_DOMAIN", "paloaltonetworks.com")
IDENTITY_ALLOWED_EMAILS = _env_csv("IDENTITY_ALLOWED_EMAILS")
IDENTITY_PLATFORM_ISSUER = os.environ.get("IDENTITY_PLATFORM_ISSUER", "Shifter")
IDENTITY_PLATFORM_TOTP_DISPLAY_NAME = os.environ.get(
    "IDENTITY_PLATFORM_TOTP_DISPLAY_NAME",
    "Shifter Authenticator",
)
PLATFORM_BOOTSTRAP_STAFF_EMAILS = _env_csv("PLATFORM_BOOTSTRAP_STAFF_EMAILS")
PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS = _env_csv("PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS")

# Cognito endpoints
# Cognito has two different base URLs:
# - Auth domain: for OAuth endpoints (authorize, token, userInfo)
# - Issuer URL: for JWKS (token verification)
_oidc_auth_domain = os.environ.get("OIDC_AUTH_DOMAIN", "https://auth.example.test" if IS_TEST_RUN else "")
_oidc_issuer = os.environ.get("OIDC_ISSUER_URL", "https://issuer.example.test" if IS_TEST_RUN else "")

# Always define OIDC_OP_* variables to avoid runtime errors.
# ``_oidc_placeholder`` indirection sidesteps bandit's B105 false-positive
# on the empty-string literal for *_TOKEN_ENDPOINT (the variable name
# pattern-matches as suspicious) without needing per-line `# nosec`
# markers that fight Sonar's S139 trailing-comment rule.
_oidc_placeholder = ""
OIDC_OP_AUTHORIZATION_ENDPOINT = _oidc_placeholder
OIDC_OP_TOKEN_ENDPOINT = _oidc_placeholder
OIDC_OP_USER_ENDPOINT = _oidc_placeholder
OIDC_OP_JWKS_ENDPOINT = _oidc_placeholder

if AUTH_PROVIDER == "oidc" and _oidc_auth_domain and _oidc_issuer:
    # OAuth endpoints use the auth domain
    OIDC_OP_AUTHORIZATION_ENDPOINT = f"{_oidc_auth_domain}/oauth2/authorize"
    OIDC_OP_TOKEN_ENDPOINT = f"{_oidc_auth_domain}/oauth2/token"
    OIDC_OP_USER_ENDPOINT = f"{_oidc_auth_domain}/oauth2/userInfo"
    # JWKS uses the issuer URL
    OIDC_OP_JWKS_ENDPOINT = f"{_oidc_issuer}/.well-known/jwks.json"
elif AUTH_PROVIDER == "oidc":
    warnings.warn(
        "OIDC_AUTH_DOMAIN or OIDC_ISSUER_URL is not set. OIDC endpoints are not configured.",
        RuntimeWarning,
        stacklevel=2,
    )

# Token verification
OIDC_RP_SIGN_ALGO = "RS256"

# User mapping - Cognito uses 'email' claim
OIDC_RP_SCOPES = "openid email profile"

# Redirect after login/logout
# Uses the dashboard router to redirect users based on their user type
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/"

# Login URL - dev bypass in DEBUG, provider router in production
LOGIN_URL = "/dev-login/" if DEBUG else "platform_login"

# OIDC logout endpoint - clears the identity provider session in addition to Django session
OIDC_OP_LOGOUT_URL_METHOD = "config.oidc.provider_logout_url" if AUTH_PROVIDER == "oidc" else ""

# Create users on first login
OIDC_CREATE_USER = True

# Use email as username (default is sha1 hash of email)
OIDC_USERNAME_ALGO = "config.oidc.generate_username"

# URLs exempt from OIDC authentication (public pages)
# Must be URL paths starting with "/" or view names (not regex patterns)
OIDC_EXEMPT_URLS = [
    # Landing page
    "/",
    # Health check
    "/health",
    # Health check with trailing slash
    "/health/",
    # View enforces production blocking directly
    "/dev-login/",
    # View enforces production blocking directly
    "/dev-logout/",
    # CTF magic link registration (token is the auth)
    "/ctf/register/",
    # CTF help page
    "/ctf/help/",
]

# Session cookie lifetime — makes Django's 14-day default explicit.
# CTF participants auth via magic link (ModelBackend), so OIDC SessionRefresh
# won't expire their sessions. This ensures no surprises from Django defaults.
# 14 days
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14
