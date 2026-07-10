"""Tests for config env manifest generation (#948)."""

from __future__ import annotations

from config._env_manifest import collect_env_bindings, manifest_is_current


def test_collect_env_bindings_includes_environment():
    names = {binding.name for binding in collect_env_bindings()}
    assert "ENVIRONMENT" in names
    assert "DJANGO_SECRET_KEY" in names
    assert "DB_HOST" in names


def test_env_manifest_is_current():
    assert manifest_is_current(), (
        "config/env-manifest.json is stale; run `python manage.py generate_env_manifest` from shifter_platform"
    )
