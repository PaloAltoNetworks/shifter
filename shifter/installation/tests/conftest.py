"""Shared fixtures for the installation package tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = PACKAGE_ROOT / "examples"


def _minimal_config() -> dict[str, Any]:
    """The smallest *schema-valid* root config (no ``secrets`` / ``settings``).

    This is enough for the root-schema tests, but it is not a complete config that
    :func:`installation.loader.load_root_config` accepts for ``aws`` — that backend
    requires secret entries (see :func:`aws_config`).
    """
    return {
        "backend": "aws",
        "deployment": {
            "name": "shifter",
            "domain": "shifter.example.com",
        },
    }


@pytest.fixture
def minimal_config() -> dict[str, Any]:
    return _minimal_config()


@pytest.fixture
def aws_config() -> dict[str, Any]:
    """A complete root config for the ``aws`` backend (declares the secrets aws requires)."""
    return {
        "backend": "aws",
        "deployment": {"name": "shifter", "domain": "shifter.example.com"},
        "secrets": {"django_secret_key": "prompt", "db_password": "prompt"},
    }


@pytest.fixture
def gcp_config() -> dict[str, Any]:
    """A complete root config for the ``gcp`` backend (declares the secret gcp requires)."""
    return {
        "backend": "gcp",
        "deployment": {"name": "shifter", "domain": "shifter.example.com"},
        "secrets": {"django_secret_key": "prompt"},
    }


@pytest.fixture
def full_config() -> dict[str, Any]:
    return {
        "version": 1,
        "backend": "gcp",
        "deployment": {
            "name": "acme-range",
            "domain": "range.acme.example.com",
            "profile": "prod",
        },
        "secrets": {
            "django_secret_key": "shifter/prod/django-secret-key",
            "oidc_client_secret": "projects/acme/secrets/oidc-client-secret",
        },
        "settings": {
            "region": "us-central1",
            "project_id": "acme-shifter",
        },
    }


@pytest.fixture
def examples_dir() -> Path:
    return EXAMPLES_DIR


@pytest.fixture
def write_config(tmp_path: Path) -> Callable[..., Path]:
    """Return a factory that serialises a mapping to ``shifter.yaml`` under tmp_path.

    Pass ``raw=<str>`` to write arbitrary file content instead of YAML-dumping a mapping
    (used to exercise the YAML-parse error path).
    """

    def _write(data: Any | None = None, *, name: str = "shifter.yaml", raw: str | None = None) -> Path:
        path = tmp_path / name
        if raw is not None:
            path.write_text(raw, encoding="utf-8")
        else:
            path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return path

    return _write
