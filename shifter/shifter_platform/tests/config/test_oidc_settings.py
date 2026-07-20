"""Tests for OIDC settings requiredness."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PLATFORM_DIR = Path(__file__).resolve().parents[2]
SHIFTER_DIR = PLATFORM_DIR.parent


def _oidc_import_env(**updates: str) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "AUTH_PROVIDER",
            "DJANGO_SETTINGS_MODULE",
            "DJANGO_DEBUG",
            "ENVIRONMENT",
            "OIDC_AUTH_DOMAIN",
            "OIDC_ISSUER_URL",
            "OIDC_RP_CLIENT_ID",
            "OIDC_RP_CLIENT_SECRET",
            "TESTING",
        }
    }
    env.update(
        {
            "PYTHONPATH": os.pathsep.join([str(PLATFORM_DIR), str(SHIFTER_DIR)]),
            "AUTH_PROVIDER": "oidc",
            "DJANGO_DEBUG": "false",
            "ENVIRONMENT": "production",
        }
    )
    env.update(updates)
    return env


def _run_oidc_import(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", "import config._oidc_settings"],
        env=env,
        cwd=PLATFORM_DIR,
        capture_output=True,
        text=True,
        check=False,
    )


def test_oidc_provider_requires_production_client_and_endpoints() -> None:
    result = _run_oidc_import(_oidc_import_env())

    assert result.returncode != 0
    assert "OIDC_RP_CLIENT_ID" in result.stderr + result.stdout


def test_oidc_provider_imports_with_complete_production_env() -> None:
    result = _run_oidc_import(
        _oidc_import_env(
            OIDC_RP_CLIENT_ID="client-id",
            OIDC_RP_CLIENT_SECRET="client-secret",
            OIDC_AUTH_DOMAIN="https://auth.example.test",
            OIDC_ISSUER_URL="https://issuer.example.test",
        )
    )

    assert result.returncode == 0, result.stderr + result.stdout


def test_identity_platform_does_not_require_oidc_runtime_values() -> None:
    result = _run_oidc_import(_oidc_import_env(AUTH_PROVIDER="identity_platform"))

    assert result.returncode == 0, result.stderr + result.stdout


def _run_oidc_issuer_print(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", "import config._oidc_settings as s; print(repr(s.OIDC_ISSUER_URL))"],
        env=env,
        cwd=PLATFORM_DIR,
        capture_output=True,
        text=True,
        check=False,
    )


def test_oidc_issuer_url_is_exported_as_module_setting() -> None:
    """The OIDC adapter's issuer check (issue #1521) reads settings.OIDC_ISSUER_URL,
    so the module-level env read must be promoted to a real exported setting."""
    assert "OIDC_ISSUER_URL" in __import__("config._oidc_settings", fromlist=["__all__"]).__all__

    result = _run_oidc_issuer_print(
        _oidc_import_env(
            OIDC_RP_CLIENT_ID="client-id",
            OIDC_RP_CLIENT_SECRET="client-secret",
            OIDC_AUTH_DOMAIN="https://auth.example.test",
            OIDC_ISSUER_URL="https://issuer.example.test",
        )
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stdout.strip() == "'https://issuer.example.test'"


def test_oidc_issuer_url_defaults_to_empty_placeholder_outside_oidc_provider() -> None:
    result = _run_oidc_issuer_print(_oidc_import_env(AUTH_PROVIDER="identity_platform"))

    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stdout.strip() == "''"
