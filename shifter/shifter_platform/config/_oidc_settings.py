"""OIDC / Identity-Platform / Cognito Django settings.

Extracted from ``config/settings.py`` to keep that module under the
500-line cap (Sonar S104). Reads the same environment variables as the
old inline block; importing this module has no side effects beyond
binding the module-level constants used in the re-export.
"""

from __future__ import annotations

import os

from config._runtime_env import AUTH_PROVIDER, required_runtime_env

__all__ = [
    "AUTHENTICATION_BACKENDS",
    "CTF_LOGIN_RATE_LIMIT_MAX",
    "CTF_LOGIN_RATE_LIMIT_WINDOW_SECONDS",
    "CTF_LOGIN_SOURCE_RATE_LIMIT_MAX",
    "CTF_ORGANIZER_PROVIDER_GROUPS",
    "CTF_PARTICIPANT_ACCOUNT_RETENTION_HOURS",
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
    "OIDC_CREATE_USER",
    "OIDC_EXEMPT_URLS",
    "OIDC_ISSUER_URL",
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
        "config.auth.PlatformModelBackend",
        "config.auth.CTFParticipantBackend",
    ]
else:
    AUTHENTICATION_BACKENDS = [
        "config.oidc.ShifterOIDCBackend",
        "config.auth.PlatformModelBackend",
        "config.auth.CTFParticipantBackend",
    ]

CTF_PARTICIPANT_ACCOUNT_RETENTION_HOURS = int(os.environ.get("CTF_PARTICIPANT_ACCOUNT_RETENTION_HOURS", "24"))
CTF_LOGIN_RATE_LIMIT_MAX = int(os.environ.get("CTF_LOGIN_RATE_LIMIT_MAX", "5"))
CTF_LOGIN_SOURCE_RATE_LIMIT_MAX = int(os.environ.get("CTF_LOGIN_SOURCE_RATE_LIMIT_MAX", "100"))
CTF_LOGIN_RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("CTF_LOGIN_RATE_LIMIT_WINDOW_SECONDS", "300"))

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

# Verified, administrator-controlled provider group names that grant the local
# ``CTF Organizer`` group at login (issue #1516). Organizer authority is never
# derivable from self-service identity/profile data; it comes only from these
# admin-managed provider groups (mapped in ``config.organizer_authority``) or
# explicit local assignment. Provider group names are case-sensitive, so this
# uses the case-preserving parser. Fail-closed: unset grants no organizer via the
# provider path (local Django-admin assignment still works).
CTF_ORGANIZER_PROVIDER_GROUPS = _env_list("CTF_ORGANIZER_PROVIDER_GROUPS")

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
# Expected ID-token issuer for config.oidc.ShifterOIDCBackend.verify_token's
# exact-match check (issue #1521). Placeholder outside AUTH_PROVIDER="oidc" so
# the setting always exists; mozilla-django-oidc's base verify_token does not
# check this itself (it decodes with verify_aud=False and is not given an
# expected issuer), so the adapter validates it explicitly against this value.
OIDC_ISSUER_URL = _oidc_placeholder

if AUTH_PROVIDER == "oidc":
    # Cognito has two different base URLs:
    # - Auth domain: for OAuth endpoints (authorize, token, userInfo)
    # - Issuer URL: for JWKS (token verification)
    _oidc_auth_domain = required_runtime_env("OIDC_AUTH_DOMAIN", dev_default="https://auth.example.test")
    _oidc_issuer = required_runtime_env("OIDC_ISSUER_URL", dev_default="https://issuer.example.test")
    OIDC_ISSUER_URL = _oidc_issuer
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
    # Dedicated local CTF participant authentication (still CSRF protected)
    "/ctf/login/",
    "/ctf/change-password/",
    # CTF help page
    "/ctf/help/",
    # Exact invitation fragment exchange endpoints; no wildcard exemptions.
    "/workspace-invitations/accept/",
    "/workspace-invitations/stage/",
]

# Session cookie lifetime — makes Django's 14-day default explicit. Temporary
# CTF sessions are additionally bounded by the live-event account policy.
# 14 days
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14
