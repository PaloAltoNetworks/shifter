"""
Django settings for Shifter platform.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
AUTH_PROVIDER = os.environ.get("AUTH_PROVIDER", "oidc").strip().lower()
IS_TEST_RUN = os.environ.get("TESTING") == "1" or Path(sys.argv[0]).name == "pytest"


def _env_bool(name: str, default: bool = False) -> bool:
    """Parse boolean environment variables using explicit true/false strings."""
    return os.environ.get(name, str(default)).lower() == "true"


def _env_csv(name: str) -> list[str]:
    """Parse comma-separated environment variables into normalized lists."""
    return [item.strip().lower() for item in os.environ.get(name, "").split(",") if item.strip()]


def _env_list(name: str) -> list[str]:
    """Parse comma-separated environment variables into stripped string lists."""
    return [item.strip() for item in os.environ.get(name, "").split(",") if item.strip()]


# Security
_test_secret_key_default = "django-tests-secret-key" if IS_TEST_RUN else None

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", _test_secret_key_default)
if not SECRET_KEY:
    raise ValueError("DJANGO_SECRET_KEY environment variable is required")
DEBUG = _env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
# Required for debug context processor
INTERNAL_IPS = ["127.0.0.1"]

# Field encryption key for sensitive model fields (e.g., SCMCredential.scm_pin_value)
# Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# For testing, use a deterministic key; in production, use FIELD_ENCRYPTION_KEY env var
FIELD_ENCRYPTION_KEY = os.environ.get(
    "FIELD_ENCRYPTION_KEY",
    # Test-only default - not used in production (FIELD_ENCRYPTION_KEY env var is required).
    # Empty-string (not None) when neither env nor test mode applies so the
    # type stays `str` for consumers like `cms.credential_encryption`. The
    # production fail-closed check on the second FIELD_ENCRYPTION_KEY block
    # below treats an empty string as "unset" and raises.
    "VbMOEgh9VmS5lr0EsIS2sD9X1iy-Qd12i4kVZHdgPVE="  # NOSONAR - test-only key, not a production credential
    if IS_TEST_RUN
    else "",
)
_csrf_origins = os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "")
CSRF_TRUSTED_ORIGINS = [o.strip() for o in _csrf_origins.split(",") if o.strip()]

# Site URL for internal callbacks (e.g., provisioner callback)
# Required in all environments - no default fallback
SITE_URL = os.environ.get("SITE_URL")

# Application definition
INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "channels",
    "health_check",
    "health_check.db",
    "health_check.cache",
    "health_check.storage",
    "rest_framework",
    "mission_control.apps.MissionControlConfig",
    "risk_register.apps.RiskRegisterConfig",
    "documentation.apps.DocumentationConfig",
    "engine.apps.EngineConfig",
    "cms.apps.CMSConfig",
    "management.apps.ManagementConfig",
    "shared.apps.SharedConfig",
    "cms.experiments.apps.ExperimentsConfig",
    "ctf.apps.CtfConfig",
]

if AUTH_PROVIDER == "oidc":
    INSTALLED_APPS.append("mozilla_django_oidc")

MIDDLEWARE = [
    # Must be first to bypass ALLOWED_HOSTS for ALB
    "config.middleware.HealthCheckMiddleware",
    # Request ID for audit logging correlation
    "config.middleware.RequestIDMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# OIDC SessionRefresh middleware - only for the OIDC/Cognito auth path.
if not DEBUG and AUTH_PROVIDER == "oidc":
    if not (os.environ.get("OIDC_RP_CLIENT_ID") or IS_TEST_RUN):
        raise ValueError("OIDC_RP_CLIENT_ID required in production (DEBUG=False)")
    MIDDLEWARE.append("mozilla_django_oidc.middleware.SessionRefresh")

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "mission_control.context_processors.active_range",
                "mission_control.context_processors.terminal_cdn_assets",
                "shared.context_processors.user_permissions",
                "ctf.context_processors.ctf_navigation",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ------------------------------------------------------------------------------
# Django Channels Configuration
# ------------------------------------------------------------------------------


# Redis for the channel layer (multi-instance pod deployment).
#
# Three runtime postures, in order of preference, derived from the env:
#   1. REDIS_HOST empty       -> InMemoryChannelLayer (local dev,
#                                pytest runs without a Redis dependency).
#   2. REDIS_HOST set, no TLS -> channels_redis tuple host form (plaintext
#                                Redis on a private network — the AWS and
#                                pre-#963 GCP shape).
#   3. REDIS_HOST + REDIS_TLS -> rediss://<password>@host:port/0 URL host.
#                                REDIS_PASSWORD is hydrated by entrypoint.sh
#                                from Secret Manager (ADR-008-R6).
#
# Fail closed when the TLS flag is on but no password was hydrated — silent
# fallback to plaintext is the failure mode #963 was opened to close.
def _build_channel_layers(env: Mapping[str, str]) -> dict[str, dict[str, object]]:
    """Build CHANNEL_LAYERS from the given mapping (typically os.environ).

    Pure function so it is unit-testable without touching real settings.
    """
    from django.core.exceptions import ImproperlyConfigured

    host = env.get("REDIS_HOST", "").strip()
    if not host:
        return {
            "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
        }

    port = int(env.get("REDIS_PORT", "6379"))
    tls = env.get("REDIS_TLS", "").strip().lower() == "true"
    if tls:
        password = env.get("REDIS_PASSWORD", "").strip()
        if not password:
            raise ImproperlyConfigured(
                "REDIS_TLS=true requires REDIS_PASSWORD (hydrated by entrypoint.sh "
                "from Secret Manager); refusing to fall back to a plaintext connection"
            )
        # channels_redis (>= 4) accepts dict-form host entries; the dict is
        # unpacked into `aioredis.ConnectionPool.from_url(address, **rest)`
        # (see channels_redis/utils.py::create_pool), so redis-py's SSL
        # kwargs flow through. SERVER_AUTHENTICATION on GCP Memorystore
        # needs the instance CA to verify the server cert — when present,
        # the CA PEM is passed via `ssl_ca_data` so we never have to write
        # the cert to disk or mutate the system trust store. When absent
        # (tests, or environments that haven't shipped the CA bundle yet),
        # redis-py falls back to the system trust store with cert_reqs
        # still required.
        ca_pem = env.get("REDIS_CA_PEM", "")
        if not ca_pem.strip():
            # ADR-008-R6 fail-closed: the GCP runtime delivers the
            # Memorystore server CA alongside the AUTH token in Secret
            # Manager, and entrypoint.sh exports both as a unit. If the
            # CA didn't make it into the env, either Terraform hasn't
            # been re-applied with the new payload yet or the entrypoint
            # block was bypassed — both are misconfigurations, not
            # "fall back to system trust" cases. Memorystore uses a
            # private CA, so the system trust store could not validate
            # the cert anyway; this guard surfaces the misconfiguration
            # at startup rather than as an opaque TLS handshake failure
            # later.
            raise ImproperlyConfigured(
                "REDIS_TLS=true requires REDIS_CA_PEM (hydrated by entrypoint.sh "
                "from the Memorystore server_ca_cert in Secret Manager); refusing "
                "to fall back to the system trust store, which cannot validate the "
                "Memorystore private CA"
            )
        address = f"rediss://:{password}@{host}:{port}/0"
        # Use the raw CA value (do not strip) — the PEM block's
        # trailing newline matters for some TLS implementations and the
        # canonical form ends with one.
        host_entry = {
            "address": address,
            "ssl_cert_reqs": "required",
            "ssl_ca_data": ca_pem,
        }
        hosts: list[object] = [host_entry]
    else:
        hosts = [(host, port)]

    return {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": hosts},
        },
    }


REDIS_HOST = os.environ.get("REDIS_HOST", "")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
CHANNEL_LAYERS = _build_channel_layers(os.environ)

# Database
# Use SQLite for local dev/tests, PostgreSQL for deployed environments
if os.environ.get("TESTING") == "1":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DB_NAME", "shifter"),
            "USER": os.environ.get("DB_USER"),
            "PASSWORD": os.environ.get("DB_PASSWORD"),
            "HOST": os.environ.get("DB_HOST", "localhost"),
            "PORT": os.environ.get("DB_PORT", "5432"),
            # Connection settings (can tune CONN_MAX_AGE for connection reuse)
            "CONN_MAX_AGE": 0,
            "OPTIONS": {
                "connect_timeout": 10,
            },
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
LOCALE_PATHS = [BASE_DIR / "locale"]
USE_TZ = True

# Static files
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

# Use simple static storage for tests (no manifest required)
if os.environ.get("TESTING") == "1":
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
else:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }

# Terminal CDN assets (xterm.js + addons + split.js). Centralised so the
# terminal template references symbolic names instead of inline absolute
# URIs (Sonar Web:S1829 hardens this surface). When bumping a pin update
# both `url` and `integrity` together.
TERMINAL_CDN_ASSETS = {
    "xterm_css": {
        "url": "https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.css",
        "integrity": "sha384-LJcOxlx9IMbNXDqJ2axpfEQKkAYbFjJfhXexLfiRJhjDU81mzgkiQq8rkV0j6dVh",
    },
    "xterm_js": {
        "url": "https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.min.js",
        "integrity": "sha384-xjfWUeCWdMtvpAb/SmM6lMzS6pQGcQa0loOl1d97j6Odw0vjK9nW3+dTb/bn/mwH",
    },
    "xterm_addon_fit": {
        "url": "https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.min.js",
        "integrity": "sha384-dpjGwSSISUTz2taP54Bor7qkyMR20sSO9oe11UVYnGs2/YdUBf7HW30XKQx9PCzn",
    },
    "xterm_addon_web_links": {
        "url": "https://cdn.jsdelivr.net/npm/xterm-addon-web-links@0.9.0/lib/xterm-addon-web-links.min.js",
        "integrity": "sha384-iAAiqSZrWZz/YKZSTKOPNaRhVOg9JY14avg2EWEpYNnUsrnATA+Sg8pV7mak84/G",
    },
    "split_js": {
        "url": "https://unpkg.com/split.js@1.6.5/dist/split.min.js",
        "integrity": "",
    },
}

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Security settings for production
if not DEBUG:
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", True)
    CSRF_COOKIE_SECURE = _env_bool("CSRF_COOKIE_SECURE", True)

    # HTTPS enforcement (issue #776). `SECURE_PROXY_SSL_HEADER` above tells
    # Django to read the LB's forwarded-proto, so `SECURE_SSL_REDIRECT`
    # won't loop behind a TLS-terminating proxy. Health-check probes that
    # arrive over plain HTTP without `X-Forwarded-Proto: https` will 301;
    # add their paths to `SECURE_REDIRECT_EXEMPT` via env if the LB
    # doesn't follow redirects.
    SECURE_SSL_REDIRECT = _env_bool("SECURE_SSL_REDIRECT", True)

    # HSTS — defense in depth so an active downgrade can't strip the first
    # redirect. Defaults: 1 year, include subdomains, NO preload. Preload
    # is opt-in because submission to the browser-baked preload list is
    # near-irreversible (chromium docs: weeks-to-months to remove); only
    # enable once you actually intend to submit chrome://net-internals.
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", True)
    SECURE_HSTS_PRELOAD = _env_bool("SECURE_HSTS_PRELOAD", False)

# ------------------------------------------------------------------------------
# Authentication
# ------------------------------------------------------------------------------

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
MAGIC_LINK_SINGLE_USE = _env_bool("MAGIC_LINK_SINGLE_USE", False)

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
else:
    import warnings

    if AUTH_PROVIDER == "oidc":
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

# ------------------------------------------------------------------------------
# Field Encryption (django-encrypted-model-fields)
# ------------------------------------------------------------------------------
# Used for encrypting sensitive credential fields (SCM PINs, authcodes)
# Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# In production: stored in Secrets Manager alongside other platform secrets

FIELD_ENCRYPTION_KEY = os.environ.get("FIELD_ENCRYPTION_KEY", "")
if not FIELD_ENCRYPTION_KEY:
    if DEBUG or IS_TEST_RUN:
        # Dev/test default - not a production credential
        FIELD_ENCRYPTION_KEY = "YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY="  # NOSONAR - dev/test-only key
    else:
        raise ValueError("FIELD_ENCRYPTION_KEY environment variable is required in production")

# ------------------------------------------------------------------------------
# Shifter Configuration
# ------------------------------------------------------------------------------

SHIFTER_SUPPORT_EMAIL = os.environ.get("SHIFTER_SUPPORT_EMAIL", "noreply@shifter.local")  # NOSONAR

# Provisioning timeout - how long dashboard waits before showing timeout error
# UI fallback is 60 min if not provided (avoids long range standup issues during testing)
# 30 minutes
PROVISIONING_TIMEOUT_MS = 30 * 60 * 1000

# ------------------------------------------------------------------------------
# Cloud Provider Configuration
# ------------------------------------------------------------------------------

# Which cloud provider to use: "aws" (default) or "gcp" (future)
CLOUD_PROVIDER = os.environ.get("CLOUD_PROVIDER", "aws")
GOOGLE_CLOUD_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID") or GOOGLE_CLOUD_PROJECT
GCP_REGION = os.environ.get("GCP_REGION") or os.environ.get("CLOUD_REGION", "")

# Generic names — adapters use these; AWS-specific names kept as fallbacks
CLOUD_REGION = (
    os.environ.get("CLOUD_REGION") or os.environ.get("AWS_REGION") or os.environ.get("AWS_S3_REGION", "us-east-2")
)
STORAGE_BUCKET_NAME = os.environ.get("STORAGE_BUCKET_NAME") or os.environ.get("AWS_S3_BUCKET_NAME", "")

# ------------------------------------------------------------------------------
# AWS S3 Configuration
# ------------------------------------------------------------------------------

# Backward compat alias
AWS_S3_BUCKET_NAME = STORAGE_BUCKET_NAME
# Backward compat alias
AWS_S3_REGION = CLOUD_REGION
# Backward compat alias
AWS_REGION = CLOUD_REGION
# LocalStack support
AWS_ENDPOINT_URL = os.environ.get("AWS_ENDPOINT_URL", "")

# Topic for publishing events (provisioner -> workers)
RANGE_EVENTS_TOPIC_ID = os.environ.get("RANGE_EVENTS_TOPIC_ID") or os.environ.get("SNS_RANGE_EVENTS_ARN", "")
# Backward compat alias
SNS_RANGE_EVENTS_ARN = RANGE_EVENTS_TOPIC_ID

# Shifter Engine task runner configuration.
# AWS uses ECS-compatible values. GCP uses a Kubernetes namespace plus a
# container image that the GKE-native task runner launches as a Job.
ENGINE_TASK_CLUSTER = (
    os.environ.get("ENGINE_TASK_NAMESPACE")
    or os.environ.get("ENGINE_TASK_CLUSTER")
    or os.environ.get("ENGINE_JOB_LOCATION")
    or os.environ.get("ENGINE_ECS_CLUSTER_ARN")
    or os.environ.get("PULUMI_ECS_CLUSTER_ARN", "")
)
ENGINE_TASK_DEFINITION = (
    os.environ.get("ENGINE_TASK_DEFINITION")
    or os.environ.get("ENGINE_TASK_IMAGE")
    or os.environ.get("ENGINE_TASK_DEFINITION_ARN")
    or os.environ.get("PULUMI_TASK_DEFINITION_ARN", "")
)
ENGINE_TASK_SERVICE_ACCOUNT_NAME = os.environ.get("ENGINE_TASK_SERVICE_ACCOUNT_NAME", "")
ENGINE_TASK_IMAGE_PULL_POLICY = os.environ.get("ENGINE_TASK_IMAGE_PULL_POLICY", "IfNotPresent")
ENGINE_TASK_BACKOFF_LIMIT = int(os.environ.get("ENGINE_TASK_BACKOFF_LIMIT", "0"))
ENGINE_TASK_TTL_SECONDS_AFTER_FINISHED = int(os.environ.get("ENGINE_TASK_TTL_SECONDS_AFTER_FINISHED", "3600"))
ENGINE_TASK_NETWORK_SECURITY_GROUP_ID = (
    os.environ.get("ENGINE_TASK_NETWORK_SECURITY_GROUP_ID")
    or os.environ.get("ENGINE_ECS_SECURITY_GROUP_ID")
    or os.environ.get("PULUMI_ECS_SECURITY_GROUP_ID", "")
)
ENGINE_TASK_NETWORK_SUBNET_IDS = (
    os.environ.get("ENGINE_TASK_NETWORK_SUBNET_IDS")
    or os.environ.get("ENGINE_PRIVATE_SUBNET_IDS")
    or os.environ.get("PULUMI_PRIVATE_SUBNET_IDS", "")
)

# Backward compat aliases for existing AWS call sites and tests
ENGINE_ECS_CLUSTER_ARN = ENGINE_TASK_CLUSTER
ENGINE_TASK_DEFINITION_ARN = ENGINE_TASK_DEFINITION
ENGINE_ECS_SECURITY_GROUP_ID = ENGINE_TASK_NETWORK_SECURITY_GROUP_ID
ENGINE_PRIVATE_SUBNET_IDS = ENGINE_TASK_NETWORK_SUBNET_IDS
EXPERIMENT_TASK_DEFINITION = os.environ.get("EXPERIMENT_TASK_DEFINITION") or os.environ.get(
    "EXPERIMENT_TASK_DEFINITION_ARN", ""
)
EXPERIMENT_TASK_DEFINITION_ARN = EXPERIMENT_TASK_DEFINITION

# Local Provisioner (for local dev - runs provisioner as subprocess instead of ECS)
LOCAL_PROVISIONER = os.environ.get("LOCAL_PROVISIONER", "")
PROVISIONER_PATH = os.environ.get("PROVISIONER_PATH", "")

# Agent upload limits
# 2GB max per file
AGENT_MAX_FILE_SIZE_MB = 2048
# 5GB max per user
AGENT_USER_STORAGE_QUOTA_MB = 5120
# 10 minutes for presigned URL
AGENT_UPLOAD_URL_EXPIRES = 600

# Experiment script upload limits
# 1MB max per script
SCRIPT_MAX_FILE_SIZE_BYTES = 1 * 1024 * 1024
# 10 minutes for presigned URL
SCRIPT_UPLOAD_URL_EXPIRES = 600

# Server-side upload inspection (issue #696). Provider-neutral byte budget for
# the magic-byte header read performed at finalization across CTF, agent, and
# experiment-script uploads. The floor is dictated by the largest registered
# offset signature (POSIX tar's ``ustar`` marker at offset 257 needs 262 bytes);
# 512 comfortably covers it with slack. Sub-floor or non-positive overrides
# (env mis-set to 0/-1) clamp to the floor so the adapter never raises
# ``ValueError`` from an invalid runtime config, and so offset-based formats
# remain inspectable.
_UPLOAD_INSPECTION_FLOOR = 512
try:
    _UPLOAD_INSPECTION_RAW = int(os.environ.get("UPLOAD_INSPECTION_MAX_HEADER_BYTES", str(_UPLOAD_INSPECTION_FLOOR)))
except ValueError:
    _UPLOAD_INSPECTION_RAW = _UPLOAD_INSPECTION_FLOOR
UPLOAD_INSPECTION_MAX_HEADER_BYTES = max(_UPLOAD_INSPECTION_RAW, _UPLOAD_INSPECTION_FLOOR)

# Experiment execution limits
EXPERIMENT_MAX_TOTAL_RUNS = 10
EXPERIMENT_MAX_PARALLEL_RUNS = 5

# Guacamole RDP Integration
# ------------------------------------------------------------------------------
# JSON auth secret key for signing RDP session URLs
# Must match the JSON_SECRET_KEY configured in Guacamole's ECS task definition
# This is a hex string key (64-character/256-bit preferred) stored in Secrets Manager
GUACAMOLE_JSON_AUTH_SECRET = os.environ.get("GUACAMOLE_JSON_AUTH_SECRET", "")
# Public URL for browser (returned to client)
GUACAMOLE_BASE_URL = os.environ.get("GUACAMOLE_BASE_URL", "/guacamole")
# Internal URL for server-to-server API calls (defaults to base URL if not set)
GUACAMOLE_API_BASE_URL = os.environ.get("GUACAMOLE_API_BASE_URL", "") or GUACAMOLE_BASE_URL

# ------------------------------------------------------------------------------
# SQS Worker Configuration
# ------------------------------------------------------------------------------
# Queue identifiers are passed via environment variables by the deployment workflow.
# On AWS the consumer and publisher both use the same SQS URL. On GCP workers
# consume Pub/Sub subscriptions while publishers target topics, so the config
# allows those identifiers to diverge without changing existing AWS call sites.


def _build_queue_config(name: str, legacy_env: str, handler: str) -> dict[str, str]:
    """Read consumer/publisher IDs for a named queue, honoring legacy env-var aliases."""
    consumer_id = (
        os.environ.get(f"QUEUE_{name}_CONSUMER_ID")
        or os.environ.get(f"QUEUE_{name}_ID")
        or os.environ.get(legacy_env, "")
    )
    publisher_id = (
        os.environ.get(f"QUEUE_{name}_PUBLISHER_ID") or os.environ.get(f"QUEUE_{name}_TOPIC_ID") or consumer_id
    )
    return {
        "url": consumer_id,
        "consumer_id": consumer_id,
        "publisher_id": publisher_id,
        "handler": handler,
    }


QUEUE_CONFIG = {
    "cms": _build_queue_config("CMS", "SQS_CMS_URL", "cms.handlers.process_event"),
    "engine": _build_queue_config("ENGINE", "SQS_ENGINE_URL", "engine.handlers.process_event"),
    "mc": _build_queue_config("MC", "SQS_MC_URL", "mission_control.handlers.process_event"),
    "experiments": _build_queue_config(
        "EXPERIMENTS",
        "SQS_EXPERIMENTS_URL",
        "cms.experiments.handlers.process_event",
    ),
}
# Backward compat alias
SQS_QUEUE_CONFIG = QUEUE_CONFIG

# ------------------------------------------------------------------------------
# CTF Configuration
# ------------------------------------------------------------------------------

CTF_FROM_EMAIL = os.environ.get("CTF_FROM_EMAIL", "ctf@example.com")
CTF_DEFAULT_RANGE_SPINUP_MINUTES = int(os.environ.get("CTF_DEFAULT_RANGE_SPINUP_MINUTES", "30"))
CTF_DEFAULT_CLEANUP_DELAY_HOURS = int(os.environ.get("CTF_DEFAULT_CLEANUP_DELAY_HOURS", "24"))
CTFD_PLATFORM_URL = os.environ.get("CTFD_PLATFORM_URL", "https://ctf.shifter.example.com/login")

# Email - SES
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
AWS_SES_REGION_NAME = "us-east-2"
AWS_SES_REGION_ENDPOINT = "email.us-east-2.amazonaws.com"

# ------------------------------------------------------------------------------
# Django REST Framework Configuration
# ------------------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "risk_register.api.authentication.APIKeyAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
}

# ------------------------------------------------------------------------------
# Environment
# ------------------------------------------------------------------------------

ENVIRONMENT = os.environ.get("ENVIRONMENT", "production")
DEV_LOGIN_ALLOWED_HOSTS = _env_list("DEV_LOGIN_ALLOWED_HOSTS") or ["localhost", "127.0.0.1", "[::1]"]
DEV_LOGIN_ALLOWED_CIDRS = _env_list("DEV_LOGIN_ALLOWED_CIDRS")

# ------------------------------------------------------------------------------
# Logging Configuration
# ------------------------------------------------------------------------------
# ECS-formatted logging for XDR/XSIAM ingestion
# See config/logging.py for ECSFormatter implementation
# Import must be inline to avoid E402 (settings.py is special)

# Log level: DEBUG for dev, INFO for production
# Set LOG_LEVEL=DEBUG in dev to see routing/tracing logs
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "ecs": {
            "()": "config.logging.ECSFormatter",
        },
        "verbose": {
            "format": "{levelname} {asctime} {module} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "ecs",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            # Keep Django framework logs at INFO
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.security": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "mission_control": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "engine": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "cms": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "cms.experiments": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "config": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "ctf": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
    },
}
