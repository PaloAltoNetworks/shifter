"""OIDC / Identity-Platform / Cognito Django settings.

Extracted from ``config/settings.py`` to keep that module under the
500-line cap (Sonar S104). Reads the same environment variables as the
old inline block; importing this module has no side effects beyond
binding the module-level constants used in the re-export.
"""

from __future__ import annotations

import os
import warnings

from config._runtime_env import AUTH_PROVIDER, IS_TEST_RUN, required_runtime_env

__all__ = [
    "AUTHENTICATION_BACKENDS",
    "IDENTITY_ALLOWED_EMAILS",
    "IDENTITY_ALLOWED_EMAIL_DOMAIN",
    "IDENTITY_PLATFORM_API_KEY",
    "IDENTITY_PLATFORM_AUTH_DOMAIN",
    "IDENTITY_PLATFORM_ISSUER",
    "IDENTITY_PLATFORM_PROJECT_ID",
    "IDENTITY_PLATFORM_TOTP_DISPLAY_NAME",
    "LOGIN_REDIRECT_URL",
    "LOGIN_URL",
    "LOGOUT_REDIRECT_URL",
    "MAGIC_LINK_EXPIRY_HOURS",
    "MAGIC_LINK_SINGLE_USE",
    "OIDC_CREATE_USER",
    "OIDC_EXEMPT_URLS",
    "OIDC_OP_AUTHORIZATION_ENDPOINT",
    "OIDC_OP_JWKS_ENDPOINT",
    "OIDC_OP_LOGOUT_URL_METHOD",
    "OIDC_OP_TOKEN_ENDPOINT",
    "OIDC_OP_USER_ENDPOINT",
    "OIDC_RP_CLIENT_ID",
    "OIDC_RP_CLIENT_SECRET",
    "OIDC_RP_SCOPES",
    "OIDC_RP_SIGN_ALGO",
    "OIDC_USERNAME_ALGO",
    "PLATFORM_BOOTSTRAP_STAFF_EMAILS",
    "PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS",
    "RISK_REGISTER_ALLOWED_COGNITO_GROUPS",
    "SESSION_COOKIE_AGE",
]

DEBUG = os.environ.get("DJANGO_DEBUG", "False").lower() == "true"


def _env_list(name: str) -> list[str]:
    """Parse comma-separated environment variables into stripped string lists."""
    return [item.strip() for item in os.environ.get(name, "").split(",") if item.strip()]


def _env_csv(name: str) -> list[str]:
    """Parse comma-separated environment variables into normalized lowercase lists."""
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

# Magic link authentication (PLAT-101). Event-backed CTF participant links use
# the event end as their expiry by default; MAGIC_LINK_EXPIRY_HOURS is the
# fallback when no event end is available. Operators that need a stricter
# event-link ceiling can set MAGIC_LINK_EVENT_MAX_EXPIRY_HOURS.
MAGIC_LINK_EXPIRY_HOURS = int(os.environ.get("MAGIC_LINK_EXPIRY_HOURS", "24"))
_MAGIC_LINK_EVENT_MAX_EXPIRY_HOURS = os.environ.get("MAGIC_LINK_EVENT_MAX_EXPIRY_HOURS")
MAGIC_LINK_EVENT_MAX_EXPIRY_HOURS = (
    int(_MAGIC_LINK_EVENT_MAX_EXPIRY_HOURS) if _MAGIC_LINK_EVENT_MAX_EXPIRY_HOURS else None
)
MAGIC_LINK_SINGLE_USE = os.environ.get("MAGIC_LINK_SINGLE_USE", "False").lower() == "true"

# OIDC settings - loaded from environment for AWS/Cognito deployments.
if AUTH_PROVIDER == "oidc":
    OIDC_RP_CLIENT_ID = required_runtime_env("OIDC_RP_CLIENT_ID", dev_default="test-oidc-client-id")
    OIDC_RP_CLIENT_SECRET = required_runtime_env("OIDC_RP_CLIENT_SECRET", dev_default="test-oidc-client-secret")
else:
    OIDC_RP_CLIENT_ID = os.environ.get("OIDC_RP_CLIENT_ID", "")
    OIDC_RP_CLIENT_SECRET = os.environ.get("OIDC_RP_CLIENT_SECRET", "")
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

if AUTH_PROVIDER == "oidc":
    # Cognito has two different base URLs:
    # - Auth domain: for OAuth endpoints (authorize, token, userInfo)
    # - Issuer URL: for JWKS (token verification)
    _oidc_auth_domain = required_runtime_env("OIDC_AUTH_DOMAIN", dev_default="https://auth.example.test")
    _oidc_issuer = required_runtime_env("OIDC_ISSUER_URL", dev_default="https://issuer.example.test")
    # OAuth endpoints use the auth domain
    OIDC_OP_AUTHORIZATION_ENDPOINT = f"{_oidc_auth_domain}/oauth2/authorize"
    OIDC_OP_TOKEN_ENDPOINT = f"{_oidc_auth_domain}/oauth2/token"
    OIDC_OP_USER_ENDPOINT = f"{_oidc_auth_domain}/oauth2/userInfo"
    # JWKS uses the issuer URL
    OIDC_OP_JWKS_ENDPOINT = f"{_oidc_issuer}/.well-known/jwks.json"

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
OIDC_USERNAME_ALGO = "config.username.generate_username"

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
    # CTF magic link token exchange (token is the auth; CSRF-protected POST)
    "/ctf/register/exchange/",
    # CTF help page
    "/ctf/help/",
]

# Session cookie lifetime — makes Django's 14-day default explicit.
# CTF participants auth via magic link (ModelBackend), so OIDC SessionRefresh
# won't expire their sessions. This ensures no surprises from Django defaults.
# 14 days
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14

# Risk register Cognito group gate (issue #151). Fail closed when unset outside tests.
RISK_REGISTER_ALLOWED_COGNITO_GROUPS = _env_list("RISK_REGISTER_ALLOWED_COGNITO_GROUPS")
if not RISK_REGISTER_ALLOWED_COGNITO_GROUPS and not IS_TEST_RUN:
    warnings.warn(
        "RISK_REGISTER_ALLOWED_COGNITO_GROUPS is unset; risk register access is denied for all principals.",
        RuntimeWarning,
        stacklevel=2,
    )
