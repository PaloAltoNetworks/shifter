"""
Django settings for Shifter portal.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# Security
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    raise ValueError("DJANGO_SECRET_KEY environment variable is required")
DEBUG = os.environ.get("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
INTERNAL_IPS = ["127.0.0.1"]  # Required for debug context processor

# Field encryption key for sensitive model fields (e.g., StrataConfig.scm_pin_value)
# Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# For testing, use a deterministic key; in production, use FIELD_ENCRYPTION_KEY env var
FIELD_ENCRYPTION_KEY = os.environ.get(
    "FIELD_ENCRYPTION_KEY",
    # Default key for testing only - NOT FOR PRODUCTION
    # pragma: allowlist secret
    "VbMOEgh9VmS5lr0EsIS2sD9X1iy-Qd12i4kVZHdgPVE=" if os.environ.get("TESTING") == "1" else None,  # nosec B105
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
    "mozilla_django_oidc",
    "rest_framework",
    "mission_control.apps.MissionControlConfig",
    "risk_register.apps.RiskRegisterConfig",
    "documentation.apps.DocumentationConfig",
]

MIDDLEWARE = [
    "config.middleware.HealthCheckMiddleware",  # Must be first to bypass ALLOWED_HOSTS for ALB
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# OIDC SessionRefresh middleware - only in production
# In DEBUG mode, we use dev_login bypass. In production, OIDC must be configured.
if not DEBUG:
    if not os.environ.get("OIDC_RP_CLIENT_ID"):
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
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ------------------------------------------------------------------------------
# Django Channels Configuration
# ------------------------------------------------------------------------------

# Redis for channel layer (multi-instance ASG deployment)
# Falls back to in-memory for local dev when REDIS_HOST not set
REDIS_HOST = os.environ.get("REDIS_HOST", "")

if REDIS_HOST:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [(REDIS_HOST, 6379)],
            },
        },
    }
else:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        },
    }

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
            "CONN_MAX_AGE": 60,
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

# ------------------------------------------------------------------------------
# OIDC Authentication (Cognito)
# ------------------------------------------------------------------------------

AUTHENTICATION_BACKENDS = [
    "config.oidc.ShifterOIDCBackend",
    "django.contrib.auth.backends.ModelBackend",
]

# Cognito OIDC settings - loaded from environment
OIDC_RP_CLIENT_ID = os.environ.get("OIDC_RP_CLIENT_ID", "")
OIDC_RP_CLIENT_SECRET = os.environ.get("OIDC_RP_CLIENT_SECRET", "")

# Cognito endpoints
# Cognito has two different base URLs:
# - Auth domain: for OAuth endpoints (authorize, token, userInfo)
# - Issuer URL: for JWKS (token verification)
_oidc_auth_domain = os.environ.get("OIDC_AUTH_DOMAIN", "")
_oidc_issuer = os.environ.get("OIDC_ISSUER_URL", "")

# Always define OIDC_OP_* variables to avoid runtime errors
OIDC_OP_AUTHORIZATION_ENDPOINT = ""  # nosec B105 - not a password, placeholder URL
OIDC_OP_TOKEN_ENDPOINT = ""  # nosec B105
OIDC_OP_USER_ENDPOINT = ""  # nosec B105
OIDC_OP_JWKS_ENDPOINT = ""  # nosec B105

if _oidc_auth_domain and _oidc_issuer:
    # OAuth endpoints use the auth domain
    OIDC_OP_AUTHORIZATION_ENDPOINT = f"{_oidc_auth_domain}/oauth2/authorize"
    OIDC_OP_TOKEN_ENDPOINT = f"{_oidc_auth_domain}/oauth2/token"
    OIDC_OP_USER_ENDPOINT = f"{_oidc_auth_domain}/oauth2/userInfo"
    # JWKS uses the issuer URL
    OIDC_OP_JWKS_ENDPOINT = f"{_oidc_issuer}/.well-known/jwks.json"
else:
    import warnings

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
LOGIN_REDIRECT_URL = "/mission-control/"
LOGOUT_REDIRECT_URL = "/"

# Login URL - dev bypass in DEBUG, OIDC in production
LOGIN_URL = "/dev-login/" if DEBUG else "oidc_authentication_init"

# Cognito logout endpoint - clears Cognito session in addition to Django session
OIDC_OP_LOGOUT_URL_METHOD = "config.oidc.provider_logout_url"

# Create users on first login
OIDC_CREATE_USER = True

# Use email as username (default is sha1 hash of email)
OIDC_USERNAME_ALGO = "config.oidc.generate_username"

# URLs exempt from OIDC authentication (public pages)
# Must be URL paths starting with "/" or view names (not regex patterns)
OIDC_EXEMPT_URLS = [
    "/",  # Landing page
    "/health",  # Health check
    "/health/",  # Health check with trailing slash
]

# ------------------------------------------------------------------------------
# Shifter Configuration
# ------------------------------------------------------------------------------

SHIFTER_SUPPORT_EMAIL = os.environ.get("SHIFTER_SUPPORT_EMAIL", "bedwards@paloaltonetworks.com")

# ------------------------------------------------------------------------------
# AWS S3 Configuration
# ------------------------------------------------------------------------------

AWS_S3_BUCKET_NAME = os.environ.get("AWS_S3_BUCKET_NAME", "")
AWS_S3_REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_S3_REGION", "us-east-2")
AWS_REGION = AWS_S3_REGION  # Alias for consistency

# Shifter Engine (ECS Fargate)
PULUMI_ECS_CLUSTER_ARN = os.environ.get("PULUMI_ECS_CLUSTER_ARN", "")
PULUMI_TASK_DEFINITION_ARN = os.environ.get("PULUMI_TASK_DEFINITION_ARN", "")
PULUMI_ECS_SECURITY_GROUP_ID = os.environ.get("PULUMI_ECS_SECURITY_GROUP_ID", "")
PULUMI_PRIVATE_SUBNET_IDS = os.environ.get("PULUMI_PRIVATE_SUBNET_IDS", "")

# Agent upload limits
AGENT_MAX_FILE_SIZE_MB = 2048  # 2GB max per file
AGENT_USER_STORAGE_QUOTA_MB = 5120  # 5GB max per user
AGENT_UPLOAD_URL_EXPIRES = 600  # 10 minutes for presigned URL

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

ENVIRONMENT = os.environ.get("ENVIRONMENT", "development")

# ------------------------------------------------------------------------------
# Logging Configuration
# ------------------------------------------------------------------------------
# ECS-formatted logging for XDR/XSIAM ingestion
# See config/logging.py for ECSFormatter implementation
# Import must be inline to avoid E402 (settings.py is special)

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
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
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
            "level": "INFO",
            "propagate": False,
        },
        "config": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
