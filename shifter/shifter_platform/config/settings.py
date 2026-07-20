"""
Django settings for Shifter platform.

Sub-sections (Channels layer, cloud/AWS task-runner + queue config,
``LOGGING`` dict, terminal CDN assets, SPA cutover rollout flags, terminal
WebSocket capacity controls) are split into ``config/_*.py`` modules and
re-imported here. The split keeps this module under Sonar S104's 500-line
cap without changing the public ``config.settings`` surface — ``from
config.settings import X`` continues to resolve every name it always has.
"""

from __future__ import annotations

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

load_dotenv()

# Sub-module re-exports. Each sub-module declares ``__all__`` so the
# wildcard surfaces only the names that are part of the public Django
# settings contract. The wildcard suppressions on each line below
# silence Sonar's S2208 (no-wildcard) guidance — for a settings module
# the wildcard *is* the contract (Django's official split-settings
# pattern uses ``from .base import *``).
from config._api_token_settings import *  # NOSONAR  # noqa: E402
from config._browser_security import *  # NOSONAR  # noqa: E402
from config._cache_settings import *  # NOSONAR  # noqa: E402
from config._channels import *  # NOSONAR  # noqa: E402
from config._channels import _build_channel_layers  # noqa: E402
from config._cloud import *  # NOSONAR  # noqa: E402
from config._drf_settings import *  # NOSONAR  # noqa: E402
from config._email import *  # NOSONAR  # noqa: E402
from config._guacamole_settings import *  # NOSONAR  # noqa: E402
from config._logging_config import *  # NOSONAR  # noqa: E402
from config._rate_limit_settings import *  # NOSONAR  # noqa: E402
from config._runtime_env import AUTH_PROVIDER, IS_TEST_RUN, require_environment, required_runtime_env  # noqa: E402
from config._terminal_assets import *  # NOSONAR  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: bool = False) -> bool:
    """Parse boolean environment variables using explicit true/false strings."""
    return os.environ.get(name, str(default)).lower() == "true"


def _env_csv(name: str) -> list[str]:
    """Parse comma-separated environment variables into normalized lists."""
    return [item.strip().lower() for item in os.environ.get(name, "").split(",") if item.strip()]


def _env_list(name: str) -> list[str]:
    """Parse comma-separated environment variables into stripped string lists."""
    return [item.strip() for item in os.environ.get(name, "").split(",") if item.strip()]


def _env_int(name: str, default: int) -> int:
    """Parse an integer environment variable, falling back to ``default``.

    An empty/unset value uses the default; a non-integer value is a
    configuration error and fails loud rather than silently degrading.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


# Security
_test_secret_key_default = "django-tests-secret-key" if IS_TEST_RUN else None

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", _test_secret_key_default)
if not SECRET_KEY:
    raise ValueError("DJANGO_SECRET_KEY environment variable is required")
# SECRET_KEY_FALLBACKS (zero-downtime rotation) lives in config._database_settings.

# Under a test run (``IS_TEST_RUN`` = ``TESTING=1`` or pytest as argv[0]) the
# posture defaults to DEBUG=True so a clean-checkout ``uv run pytest`` matches CI
# instead of inheriting the production HTTPS posture that a bare run would get
# from ``DJANGO_DEBUG`` being unset (#1529 / REV1 Q7). An explicit ``DJANGO_DEBUG``
# always wins; production (``IS_TEST_RUN`` false) is unchanged and still defaults
# to DEBUG=False. The test posture lives in config, per config._runtime_env owning
# dev/test defaults -- not in a wrapper or a value CI must inject.
DEBUG = _env_bool("DJANGO_DEBUG", IS_TEST_RUN)
ENVIRONMENT = require_environment()
_allowed_hosts_raw = required_runtime_env("DJANGO_ALLOWED_HOSTS", dev_default="localhost,127.0.0.1")
ALLOWED_HOSTS = [host.strip() for host in _allowed_hosts_raw.split(",") if host.strip()]
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must include at least one host")
# Required for debug context processor
INTERNAL_IPS = ["127.0.0.1"]

# Field encryption key for sensitive model fields (e.g., SCMCredential.scm_pin_value)
# Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Test/debug/build use a deterministic synthetic key; production must provide
# FIELD_ENCRYPTION_KEY through the entrypoint secret-hydration path.
FIELD_ENCRYPTION_KEY = required_runtime_env(
    "FIELD_ENCRYPTION_KEY",
    dev_default="YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY=",  # NOSONAR - dev/test/build synthetic key
)
_csrf_origins = os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "")
CSRF_TRUSTED_ORIGINS = [o.strip() for o in _csrf_origins.split(",") if o.strip()]

# Site URL for internal callbacks (e.g., provisioner callback)
# Required in all environments - no default fallback
SITE_URL = os.environ.get("SITE_URL")

# Public documentation site (ADR-038). Templates link out to the hosted mkdocs
# site rather than the retired in-app docs reader; kept here (config, not
# hardcoded in templates) and exposed via mission_control.context_processors.
# docs_site_url. Trailing slash so template paths append directly.
DOCS_SITE_URL = os.environ.get("DOCS_SITE_URL", "https://brad-edwards.github.io/shifter/")

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
    "config.apps.PortalConfig",
    "rest_framework",
    "drf_spectacular",
    "drf_spectacular_sidecar",
    # GCP SendGrid/Mailgun email backends (AWS uses django-ses); see config/_email.py.
    "anymail",
    "mission_control.apps.MissionControlConfig",
    "risk_register.apps.RiskRegisterConfig",
    "engine.apps.EngineConfig",
    "cms.apps.CMSConfig",
    "management.apps.ManagementConfig",
    "shared.apps.SharedConfig",
    "ctf.apps.CtfConfig",
]

if AUTH_PROVIDER == "oidc":
    INSTALLED_APPS.append("mozilla_django_oidc")

MIDDLEWARE = [
    # Must be first to bypass ALLOWED_HOSTS for ALB
    "config.middleware.HealthCheckMiddleware",
    # Request ID for audit logging correlation
    "config.middleware.RequestIDMiddleware",
    "config.middleware.RequestInFlightMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # Browser security policy (ADR-036): native CSP beside SecurityMiddleware and
    # outside WhiteNoise so legacy HTML, the SPA host, redirects, errors, APIs,
    # and static responses pass through one policy boundary. The custom
    # middleware sets only the headers Django does not own.
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "config.middleware.BrowserPolicyHeadersMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "config.middleware.CTFAccountBoundaryMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# OIDC SessionRefresh middleware - only for the OIDC/Cognito auth path.
if not DEBUG and AUTH_PROVIDER == "oidc":
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
                "mission_control.context_processors.docs_site_url",
                "config.context_processors.user_permissions",
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

# Shared WebSocket notification subsystem enablement (issue #941). The shared
# persisted notification path (``/ws/notifications/``) has no front-end consumer,
# so it is disabled by default: when off, publishing creates no per-recipient rows
# and performs no channel-layer fan-out, and the shared socket is parked. Set to
# "true" only once a real browser consumer, bounded fan-out, and scheduled pruning
# exist. Non-secret boolean; absent env means disabled.
WEBSOCKET_NOTIFICATIONS_ENABLED = _env_bool("WEBSOCKET_NOTIFICATIONS_ENABLED", False)

# SPA cutover rollout flags (issues #1302 / #1369 / #1370 / #1371 / #1372 / #1373,
# ADR-013 / ADR-029) live in config/_spa_flags_settings.py to keep this module
# under the Sonar S104 500-line cap; re-exported via star-import.
from config._spa_flags_settings import *  # noqa: E402  # NOSONAR

# Shared WebSocket notification replay bounds (issue #679).
WEBSOCKET_NOTIFICATION_MAX_REPLAY = _env_int("WEBSOCKET_NOTIFICATION_MAX_REPLAY", 100)
WEBSOCKET_NOTIFICATION_RETENTION_DAYS = _env_int("WEBSOCKET_NOTIFICATION_RETENTION_DAYS", 7)

# ------------------------------------------------------------------------------
# Terminal WebSocket capacity controls (issue #847)
# ------------------------------------------------------------------------------
# The TERMINAL_* capacity knobs live in config/_terminal_settings.py to keep
# this module under the Sonar S104 500-line cap; re-exported via star-import.
# See docs/architecture/terminal-websocket-capacity-847.md.
from config._terminal_settings import *  # noqa: E402  # NOSONAR

# Launch-endpoint rate limiting (LAUNCH_RATE_LIMIT_ENABLED, LAUNCH_RATE_LIMITS)
# lives in config/_rate_limit_settings.py (star-imported above) to keep this
# module under the Sonar S104 500-line cap; see mission_control/api/rate_limit.py.

# CTF scheduler (run_ctf_scheduler) stale-task recovery window. A long
# SPIN_UP_RANGES run heartbeats its task's updated_at, so this only needs to
# exceed the maximum gap between heartbeats; the default is set well above the
# legitimate spin-up window (default range_spinup_minutes=30) plus retry/poll
# jitter so a genuinely in-flight spin-up is never marked FAILED on the
# multi-node portal. See docs/architecture/ctf-scheduler-concurrency-preflight-942.md.
CTF_SCHEDULER_STALE_TASK_MINUTES = _env_int("CTF_SCHEDULER_STALE_TASK_MINUTES", 120)

# CTF-1003: automated range cleanup destroys ranges in batches with a pause
# between batches so a large event cannot drive the cloud APIs into
# throttling. Non-secret integers.
CTF_RANGE_CLEANUP_BATCH_SIZE = _env_int("CTF_RANGE_CLEANUP_BATCH_SIZE", 10)
CTF_RANGE_CLEANUP_BATCH_PAUSE_SECONDS = _env_int("CTF_RANGE_CLEANUP_BATCH_PAUSE_SECONDS", 5)

# ACES operation-record retention/cleanup knobs (issue #1277): snapshot TTL days
# plus the dedicated prune service cadence/batch size. Non-secret integers.
from config._aces_settings import *  # noqa: E402  # NOSONAR
from config._capacity_settings import *  # noqa: E402  # NOSONAR

# CTF regex-flag safety tunables (issue #1183): pattern/submission length caps
# and the per-match timeout that bound organizer-controlled regex evaluation.
from config._ctf_regex_settings import *  # noqa: E402  # NOSONAR

# Database and SECRET_KEY rotation settings (DATABASES, SECRET_KEY_FALLBACKS).
# Split into config/_database_settings.py to keep this module under the S104
# 500-line cap; the IAM-auth DB path lives there (issue #159).
from config._database_settings import *  # noqa: E402  # NOSONAR

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

# Default file storage needs a writable location for the
# django-health-check storage probe. Keep it out of the immutable app source
# tree so non-root production containers can prove storage readiness.
MEDIA_ROOT = BASE_DIR / "media"

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
    # won't loop behind a TLS-terminating proxy. ALB health checks arrive
    # over plain HTTP without `X-Forwarded-Proto: https` and do not follow
    # redirects, so `/health` must remain a direct dependency-aware 200/500
    # readiness surface instead of a 301.
    SECURE_SSL_REDIRECT = _env_bool("SECURE_SSL_REDIRECT", True)
    SECURE_REDIRECT_EXEMPT = [r"^health/?$"]

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
# Authentication backends, OIDC endpoint discovery, CTF local-auth config,
# and ``OIDC_EXEMPT_URLS`` are defined in ``config._oidc_settings`` so
# this module stays under the 500-line cap. Re-exported via star-import
# here (``noqa`` suppresses the unused/ambiguous-import warnings — these
# names are part of the public Django settings surface).

# OIDC env-var guard above; F401/F403 are required for star-imports of
# the public Django settings surface (the canonical split-settings idiom).
from config._oidc_settings import *  # noqa: E402  # NOSONAR

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
# Guacamole connection + bootstrap settings live in ``config/_guacamole_settings``
# (re-exported above) to keep this module under the 500-line cap (Sonar S104).

# Bounded botocore connect/read timeouts for the AWS Secrets Manager client used
# on/near the portal request path. A stalled Secrets Manager must fail fast
# instead of hanging an ASGI worker on botocore's long defaults (#929).
# AWS_SECRETS_MAX_ATTEMPTS is the total attempt count (first try + retries).
AWS_SECRETS_CONNECT_TIMEOUT_SECONDS = _env_int("AWS_SECRETS_CONNECT_TIMEOUT_SECONDS", 2)
AWS_SECRETS_READ_TIMEOUT_SECONDS = _env_int("AWS_SECRETS_READ_TIMEOUT_SECONDS", 5)
AWS_SECRETS_MAX_ATTEMPTS = _env_int("AWS_SECRETS_MAX_ATTEMPTS", 2)
# GCP counterpart: bounded per-request deadline for Secret Manager reads so a
# stalled backend fails fast instead of hanging the calling thread (#929).
GCP_SECRETS_REQUEST_TIMEOUT_SECONDS = _env_int("GCP_SECRETS_REQUEST_TIMEOUT_SECONDS", 5)

# Bounded, in-process, provider-neutral cache of resolved secret VALUES, keyed by
# secret reference (never by value), so a per-range connect storm collapses to one
# Secrets Manager fetch per reference for the TTL window (#929). TTL bounds
# staleness so credential rotation under the same reference converges and a
# destroyed range's entries simply expire; no durable storage. TTL <= 0 disables
# the cache. Values are never logged.
SECRET_CACHE_TTL_SECONDS = _env_int("SECRET_CACHE_TTL_SECONDS", 300)
SECRET_CACHE_MAX_ENTRIES = _env_int("SECRET_CACHE_MAX_ENTRIES", 256)
# First-click readiness retry for the /api/tokens exchange (issue #395).
# Bounded exponential backoff inside mission_control.guacamole guards against the
# token-readiness race that surfaces as a redirect to the Guacamole login page on
# the user's first click.
GUACAMOLE_TOKEN_RETRY_ATTEMPTS = int(os.environ.get("GUACAMOLE_TOKEN_RETRY_ATTEMPTS", "3"))
GUACAMOLE_TOKEN_RETRY_BASE_DELAY_MS = int(os.environ.get("GUACAMOLE_TOKEN_RETRY_BASE_DELAY_MS", "200"))

# ------------------------------------------------------------------------------
# Range event reconciliation (Phase 3, #476)
# ------------------------------------------------------------------------------

# Seconds a RangeInstance must remain in a non-terminal status without being
# updated before the reconciler considers it stale and re-drives the projection.
RANGE_RECONCILE_STALE_SECONDS: int = int(os.environ.get("RANGE_RECONCILE_STALE_SECONDS", "300"))

# Maximum RangeInstance rows the reconciler processes per run (bounded batch).
RANGE_RECONCILE_BATCH_SIZE: int = int(os.environ.get("RANGE_RECONCILE_BATCH_SIZE", "100"))

# ------------------------------------------------------------------------------
# CTF Configuration
# ------------------------------------------------------------------------------

CTF_FROM_EMAIL = os.environ.get("CTF_FROM_EMAIL", "ctf@example.com")
CTF_DEFAULT_RANGE_SPINUP_MINUTES = int(os.environ.get("CTF_DEFAULT_RANGE_SPINUP_MINUTES", "30"))
CTF_DEFAULT_CLEANUP_DELAY_HOURS = int(os.environ.get("CTF_DEFAULT_CLEANUP_DELAY_HOURS", "24"))
CTFD_PLATFORM_URL = os.environ.get("CTFD_PLATFORM_URL", "https://ctf.shifter.example.com/login")

# ------------------------------------------------------------------------------
# Environment
# ------------------------------------------------------------------------------

# Dev-auth admits the direct peer REMOTE_ADDR only (loopback + these CIDRs); Host is never trusted (SEC-3 #937).
DEV_LOGIN_ALLOWED_CIDRS = _env_list("DEV_LOGIN_ALLOWED_CIDRS")
# Trusted XFF proxy hops (single ALB -> 1); the audit source-IP resolver trusts that rightmost hop (SEC-4 #937).
AUDIT_TRUSTED_PROXY_HOPS = _env_int("AUDIT_TRUSTED_PROXY_HOPS", 1)

# ------------------------------------------------------------------------------
# Logging Configuration
# ------------------------------------------------------------------------------
# ECS-formatted logging for XDR/XSIAM ingestion lives in ``config.logging``
# (formatter) and ``config._logging_config`` (dictConfig). ``LOGGING`` and
# ``LOG_LEVEL`` are re-exported at the top of this file via star-equivalent
# named imports.
