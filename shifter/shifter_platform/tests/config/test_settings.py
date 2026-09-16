"""Tests for Django settings module invariants."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

SETTINGS_PATH = Path(__file__).resolve().parents[2] / "config" / "settings.py"
PLATFORM_DIR = SETTINGS_PATH.parents[1]
SHIFTER_DIR = PLATFORM_DIR.parent
REPO_ROOT = SHIFTER_DIR.parent
BOOTSTRAP_DIR = REPO_ROOT / "scripts" / "bootstrap"


def _load_settings_module(module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, SETTINGS_PATH)
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


def _settings_import_env(**updates: str | None) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"DJANGO_SETTINGS_MODULE", "TESTING", "ENVIRONMENT"}
    }
    env.update(
        {
            "DJANGO_SETTINGS_MODULE": "config.settings",
            "PYTHONPATH": os.pathsep.join([str(PLATFORM_DIR), str(SHIFTER_DIR)]),
            "DJANGO_SECRET_KEY": "settings-import-secret",
            "ENVIRONMENT": "production",
            "DJANGO_DEBUG": "false",
            "CLOUD_PROVIDER": "aws",
            "DJANGO_ALLOWED_HOSTS": "portal.example.test,localhost,127.0.0.1",
            "FIELD_ENCRYPTION_KEY": "YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY=",
            "DB_NAME": "shifter",
            "DB_USER": "portal",
            "DB_PASSWORD": "postgres-secret",
            "DB_HOST": "db.example.internal",
            "DB_PORT": "5432",
            "OIDC_RP_CLIENT_ID": "client-id",
            "OIDC_RP_CLIENT_SECRET": "client-secret",
            "OIDC_AUTH_DOMAIN": "https://auth.example.test",
            "OIDC_ISSUER_URL": "https://issuer.example.test",
            "EMAIL_BACKEND": "django.core.mail.backends.console.EmailBackend",
        }
    )
    for key, value in updates.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


def _run_settings_import(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", "import config.settings"],
        env=env,
        cwd=PLATFORM_DIR,
        capture_output=True,
        text=True,
        check=False,
    )


def test_production_settings_exempt_health_from_ssl_redirect(monkeypatch) -> None:
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("DJANGO_SECRET_KEY", "shifter-platform-tests-secret-key")
    monkeypatch.setenv("DJANGO_DEBUG", "false")

    settings_module = _load_settings_module("config._settings_production_redirect_test")

    assert settings_module.DEBUG is False
    assert settings_module.SECURE_SSL_REDIRECT is True
    assert settings_module.SECURE_REDIRECT_EXEMPT == [r"^health/?$"]


def test_production_settings_require_allowed_hosts() -> None:
    result = _run_settings_import(_settings_import_env(DJANGO_ALLOWED_HOSTS="   "))

    assert result.returncode != 0
    assert "DJANGO_ALLOWED_HOSTS" in result.stderr + result.stdout


def test_production_settings_require_effective_allowed_hosts() -> None:
    result = _run_settings_import(_settings_import_env(DJANGO_ALLOWED_HOSTS=" , , "))

    assert result.returncode != 0
    assert "DJANGO_ALLOWED_HOSTS" in result.stderr + result.stdout


def test_production_settings_require_cloud_provider() -> None:
    """A deployed portal must fail closed when CLOUD_PROVIDER is absent (PLAT-2005)."""
    result = _run_settings_import(_settings_import_env(CLOUD_PROVIDER=None))

    assert result.returncode != 0
    assert "CLOUD_PROVIDER" in result.stderr + result.stdout


def test_production_settings_reject_unsupported_cloud_provider() -> None:
    """An unsupported backend fails closed instead of behaving as AWS (PLAT-2005)."""
    result = _run_settings_import(_settings_import_env(CLOUD_PROVIDER="azure"))

    assert result.returncode != 0
    assert "CLOUD_PROVIDER" in result.stderr + result.stdout


def test_aws_eks_runtime_projection_initializes_deployed_settings(monkeypatch) -> None:
    """The rendered EKS environment reaches the deployed Django composition root."""
    monkeypatch.syspath_prepend(str(BOOTSTRAP_DIR))
    aws_eks = importlib.import_module("aws_eks")

    runtime_env = {
        "AWS_REGION": "us-east-2",
        # ENGINE_TASK_* ECS coordinates are retired (#1826); the provisioner
        # dispatches as a Kubernetes Job. The range/portal provisioner env is
        # assembled by Terraform and ENGINE_TASK_IMAGE is renderer-generated.
        "OIDC_AUTH_DOMAIN": "https://shifter-dev.auth.us-east-2.amazoncognito.com",
        "OIDC_ISSUER_URL": "https://cognito-idp.us-east-2.amazonaws.com/us-east-2_example",
        "OIDC_RP_CLIENT_ID": "example-client-id",
        "OIDC_SECRET_ID": "shifter/dev/cognito",
        "QUEUE_CMS_CONSUMER_ID": "https://sqs.us-east-2.amazonaws.com/123456789012/cms",
        "QUEUE_CMS_PUBLISHER_ID": "https://sqs.us-east-2.amazonaws.com/123456789012/cms",
        "QUEUE_ENGINE_CONSUMER_ID": "https://sqs.us-east-2.amazonaws.com/123456789012/engine",
        "QUEUE_ENGINE_PUBLISHER_ID": "https://sqs.us-east-2.amazonaws.com/123456789012/engine",
        "QUEUE_MC_CONSUMER_ID": "https://sqs.us-east-2.amazonaws.com/123456789012/mc",
        "QUEUE_MC_PUBLISHER_ID": "https://sqs.us-east-2.amazonaws.com/123456789012/mc",
        "RANGE_EVENTS_TOPIC_ID": "arn:aws:sns:us-east-2:123456789012:range-events",
        "STORAGE_BUCKET_NAME": "shifter-dev-storage",
    }
    outputs = {
        "cluster_name": {"value": "shifter-dev-eks"},
        "runtime_env": {"value": runtime_env},
        "workload_role_arns": {
            "value": {
                "ctfScheduler": "arn:aws:iam::123456789012:role/shifter-dev-ctf-scheduler",
                "ingress": "arn:aws:iam::123456789012:role/shifter-dev-ingress",
                "portal": "arn:aws:iam::123456789012:role/shifter-dev-portal",
                "workers": "arn:aws:iam::123456789012:role/shifter-dev-workers",
                "provisionerLauncher": "arn:aws:iam::123456789012:role/shifter-dev-provisioner-launcher",
                "provisioner": "arn:aws:iam::123456789012:role/shifter-dev-provisioner",
            }
        },
        "certificate_arn": {"value": "arn:aws:acm:us-east-2:123456789012:certificate/example"},
        "waf_acl_arn": {"value": "arn:aws:wafv2:us-east-2:123456789012:regional/webacl/example/id"},
        "edge_client_cidrs": {"value": ["203.0.113.0/24"]},
        "ingress_source_cidrs": {"value": ["10.42.0.0/16"]},
        "provider_api_cidrs": {"value": ["10.42.0.0/16"]},
        "private_service_cidrs": {"value": ["10.42.0.0/16"]},
        "kubernetes_api_cidrs": {"value": ["172.20.0.0/16"]},
    }
    config = SimpleNamespace(
        backend="aws",
        deployment=SimpleNamespace(
            name="shifter",
            domain="shifter.example.test",
            profile="dev",
        ),
        settings={"region": "us-east-2"},
        secrets={
            "django_secret_key": "shifter/dev/app",
            "db_password": "shifter/dev/database",
        },
    )
    digest = "a" * 64
    images = {
        "platform": f"example.invalid/shifter/platform@sha256:{digest}",
        "guacd": f"example.invalid/shifter/guacd@sha256:{digest}",
        "guacamoleClient": f"example.invalid/shifter/guacamole-client@sha256:{digest}",
        "provisioner": f"example.invalid/shifter/engine-provisioner@sha256:{digest}",
    }

    values = aws_eks.render_aws_values(config, outputs, images)
    result = _run_settings_import(
        _settings_import_env(**{key: str(value) for key, value in values["runtimeEnv"].items()})
    )

    assert result.returncode == 0, result.stderr + result.stdout


def test_field_encryption_key_has_single_settings_initializer() -> None:
    source = SETTINGS_PATH.read_text(encoding="utf-8")

    assert source.count("FIELD_ENCRYPTION_KEY =") == 1


def test_portal_capacity_metrics_defaults_are_off(monkeypatch) -> None:
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("DJANGO_SECRET_KEY", "shifter-platform-tests-secret-key")
    for var in (
        "PORTAL_CAPACITY_METRICS_ENABLED",
        "PORTAL_CAPACITY_METRICS_INTERVAL_SECONDS",
        "PORTAL_WORKER_SOFT_CONCURRENCY",
        "PORTAL_CAPACITY_NAME_PREFIX",
    ):
        monkeypatch.delenv(var, raising=False)

    # The capacity settings live in a re-exported sub-module; evict it so the
    # fresh settings load re-reads the (cleared) environment instead of the cache.
    sys.modules.pop("config._capacity_settings", None)
    settings_module = _load_settings_module("config._settings_capacity_default_test")

    assert settings_module.PORTAL_CAPACITY_METRICS_ENABLED is False
    assert settings_module.PORTAL_CAPACITY_METRICS_INTERVAL_SECONDS == 60
    assert settings_module.PORTAL_WORKER_SOFT_CONCURRENCY == 6
    assert settings_module.PORTAL_CAPACITY_NAME_PREFIX == ""
    # The in-flight middleware must be wired into the request path.
    assert "config.middleware.RequestInFlightMiddleware" in settings_module.MIDDLEWARE


def test_portal_capacity_metrics_read_from_env(monkeypatch) -> None:
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("DJANGO_SECRET_KEY", "shifter-platform-tests-secret-key")
    monkeypatch.setenv("PORTAL_CAPACITY_METRICS_ENABLED", "true")
    monkeypatch.setenv("PORTAL_CAPACITY_METRICS_INTERVAL_SECONDS", "30")
    monkeypatch.setenv("PORTAL_WORKER_SOFT_CONCURRENCY", "12")
    monkeypatch.setenv("PORTAL_CAPACITY_NAME_PREFIX", "prod-portal")

    # Re-read env in the extracted capacity-settings sub-module (avoid the cache).
    sys.modules.pop("config._capacity_settings", None)
    settings_module = _load_settings_module("config._settings_capacity_env_test")

    assert settings_module.PORTAL_CAPACITY_METRICS_ENABLED is True
    assert settings_module.PORTAL_CAPACITY_METRICS_INTERVAL_SECONDS == 30
    assert settings_module.PORTAL_WORKER_SOFT_CONCURRENCY == 12
    assert settings_module.PORTAL_CAPACITY_NAME_PREFIX == "prod-portal"


def test_api_token_policy_defaults(monkeypatch) -> None:
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("DJANGO_SECRET_KEY", "shifter-platform-tests-secret-key")
    for var in ("API_TOKEN_LAST_USED_COALESCE_SECONDS", "API_TOKEN_MAX_TTL_DAYS"):
        monkeypatch.delenv(var, raising=False)

    # Token policy lives in a re-exported sub-module; evict it so the fresh
    # settings load re-reads the (cleared) environment instead of the cache.
    sys.modules.pop("config._api_token_settings", None)
    settings_module = _load_settings_module("config._settings_api_token_default_test")

    assert settings_module.API_TOKEN_LAST_USED_COALESCE_SECONDS == 300
    assert settings_module.API_TOKEN_MAX_TTL_DAYS == 365
    # The platform token authenticator is the first DRF default.
    assert (
        settings_module.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"][0]
        == "shared.api_tokens.authentication.ApiTokenAuthentication"
    )


def test_platform_drf_convention_defaults(monkeypatch) -> None:
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("DJANGO_SECRET_KEY", "shifter-platform-tests-secret-key")

    settings_module = _load_settings_module("config._settings_platform_drf_test")

    assert "drf_spectacular" in settings_module.INSTALLED_APPS
    assert "drf_spectacular_sidecar" in settings_module.INSTALLED_APPS
    assert settings_module.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"] == [
        "shared.api_tokens.authentication.ApiTokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ]
    assert settings_module.REST_FRAMEWORK["EXCEPTION_HANDLER"] == "shared.api.errors.api_exception_handler"
    # Custom AutoSchema publishes per-operation token scopes and the shared error
    # envelope into the contract (#1329).
    assert settings_module.REST_FRAMEWORK["DEFAULT_SCHEMA_CLASS"] == "shared.api.schema.PlatformAutoSchema"
    assert settings_module.REST_FRAMEWORK["DEFAULT_VERSIONING_CLASS"] == "rest_framework.versioning.NamespaceVersioning"
    assert settings_module.REST_FRAMEWORK["ALLOWED_VERSIONS"] == ["v1"]
    assert settings_module.REST_FRAMEWORK["DEFAULT_VERSION"] == "v1"
    assert settings_module.REST_FRAMEWORK["DEFAULT_FILTER_BACKENDS"] == [
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ]

    spectacular = settings_module.SPECTACULAR_SETTINGS
    assert spectacular["TITLE"] == "Shifter Platform API"
    assert spectacular["VERSION"] == "v1"
    assert spectacular["SCHEMA_PATH_PREFIX"] == r"/api/v[0-9]+"
    assert spectacular["SERVE_INCLUDE_SCHEMA"] is False
    assert spectacular["SERVE_PERMISSIONS"] == ["shared.api.permissions.IsAuthenticatedSessionOrApiToken"]
    assert spectacular["SWAGGER_UI_DIST"] == "SIDECAR"
    assert spectacular["SWAGGER_UI_FAVICON_HREF"] == "SIDECAR"
    assert spectacular["REDOC_DIST"] == "SIDECAR"
    # Contract scoped to the SPA-facing surface: unpublished apps are dropped
    # from schema generation (#1329).
    assert spectacular["PREPROCESSING_HOOKS"] == ["shared.api.schema.exclude_unpublished_endpoints"]


def test_api_token_policy_read_from_env(monkeypatch) -> None:
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("DJANGO_SECRET_KEY", "shifter-platform-tests-secret-key")
    monkeypatch.setenv("API_TOKEN_LAST_USED_COALESCE_SECONDS", "60")
    monkeypatch.setenv("API_TOKEN_MAX_TTL_DAYS", "30")

    sys.modules.pop("config._api_token_settings", None)
    settings_module = _load_settings_module("config._settings_api_token_env_test")

    assert settings_module.API_TOKEN_LAST_USED_COALESCE_SECONDS == 60
    assert settings_module.API_TOKEN_MAX_TTL_DAYS == 30
