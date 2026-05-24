"""
Django settings for Shifter platform.

Sub-sections (Channels layer, cloud/AWS task-runner + queue config,
``LOGGING`` dict, terminal CDN assets) are split into ``config/_*.py``
modules and re-imported here. The split keeps this module under Sonar
S104's 500-line cap without changing the public ``config.settings``
surface — ``from config.settings import X`` continues to resolve every
name it always has.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Sub-module re-exports. Each sub-module declares ``__all__`` so the
# wildcard surfaces only the names that are part of the public Django
# settings contract. The wildcard suppressions on each line below
# silence Sonar's S2208 (no-wildcard) guidance — for a settings module
# the wildcard *is* the contract (Django's official split-settings
# pattern uses ``from .base import *``).
from config._channels import *  # NOSONAR
from config._channels import _build_channel_layers
from config._cloud import *  # NOSONAR
from config._logging_config import *  # NOSONAR
from config._terminal_assets import *  # NOSONAR

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
# Channel-layer construction lives in ``config._channels`` so this module
# stays under the 500-line cap. See that module's docstring for the
# AWS/GCP TLS posture matrix.
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
# Authentication backends, OIDC endpoint discovery, magic-link config,
# and ``OIDC_EXEMPT_URLS`` are defined in ``config._oidc_settings`` so
# this module stays under the 500-line cap. Re-exported via star-import
# here (``noqa`` suppresses the unused/ambiguous-import warnings — these
# names are part of the public Django settings surface).

# OIDC env-var guard above; F401/F403 are required for star-imports of
# the public Django settings surface (the canonical split-settings idiom).
from config._oidc_settings import *  # noqa: E402  # NOSONAR

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
# ECS-formatted logging for XDR/XSIAM ingestion lives in ``config.logging``
# (formatter) and ``config._logging_config`` (dictConfig). ``LOGGING`` and
# ``LOG_LEVEL`` are re-exported at the top of this file via star-equivalent
# named imports.
