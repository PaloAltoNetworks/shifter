"""Tests for config._runtime_env (#948)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured

from config._runtime_env import AUTH_PROVIDER, require_environment, resolve_cloud_provider

PLATFORM_DIR = Path(__file__).resolve().parents[2]
SHIFTER_DIR = PLATFORM_DIR.parent


def test_require_environment_raises_when_unset():
    with pytest.raises(ImproperlyConfigured, match="ENVIRONMENT is required"):
        require_environment({})


def test_require_environment_raises_when_blank():
    with pytest.raises(ImproperlyConfigured, match="ENVIRONMENT is required"):
        require_environment({"ENVIRONMENT": "   "})


def test_require_environment_returns_stripped_value():
    assert require_environment({"ENVIRONMENT": "  development  "}) == "development"


def test_settings_import_fails_without_environment():
    """Boot must fail loud when ENVIRONMENT is omitted (#948 AC1)."""
    env = {k: v for k, v in os.environ.items() if k not in {"ENVIRONMENT", "TESTING", "DJANGO_SETTINGS_MODULE"}}
    env.update(
        {
            "DJANGO_SECRET_KEY": "import-test-secret",
            "DJANGO_SETTINGS_MODULE": "config.settings",
            "PYTHONPATH": os.pathsep.join([str(PLATFORM_DIR), str(SHIFTER_DIR)]),
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", "import config.settings"],
        env=env,
        cwd=PLATFORM_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "ENVIRONMENT is required" in result.stderr + result.stdout


def test_auth_provider_default_is_oidc():
    assert AUTH_PROVIDER == "oidc"


def test_resolve_cloud_provider_returns_known_backend():
    """A registered backend is accepted and returned normalized (PLAT-2005)."""
    assert resolve_cloud_provider({"CLOUD_PROVIDER": "gcp"}) == "gcp"


def test_resolve_cloud_provider_normalizes_case_and_whitespace():
    assert resolve_cloud_provider({"CLOUD_PROVIDER": "  AWS  "}) == "aws"


def test_resolve_cloud_provider_rejects_unknown_backend():
    """An unrecognized backend fails closed rather than defaulting to AWS (PLAT-2005)."""
    with pytest.raises(ImproperlyConfigured, match="not a supported backend"):
        resolve_cloud_provider({"CLOUD_PROVIDER": "azure"})


def test_resolve_cloud_provider_allows_aws_dev_default_under_test():
    """Missing selection resolves to the aws dev default only when dev defaults are allowed."""
    assert resolve_cloud_provider({"TESTING": "1"}) == "aws"


def test_resolve_cloud_provider_fails_closed_when_missing_in_prod(monkeypatch):
    """A deployed process with no CLOUD_PROVIDER must not silently default to AWS (PLAT-2005)."""
    monkeypatch.setattr(sys, "argv", ["gunicorn"])
    with pytest.raises(ImproperlyConfigured, match="CLOUD_PROVIDER"):
        resolve_cloud_provider({"ENVIRONMENT": "production"})
