"""Tests for config env manifest generation (#948)."""

from __future__ import annotations

from config._env_manifest import collect_env_bindings, manifest_is_current


def test_collect_env_bindings_includes_environment():
    names = {binding.name for binding in collect_env_bindings()}
    assert "ENVIRONMENT" in names
    assert "DJANGO_SECRET_KEY" in names
    assert "DB_HOST" in names


def test_collect_env_bindings_includes_test_db_backend():
    """The explicit TEST_DB_BACKEND selector must appear in the manifest (#1524)."""
    names = {binding.name for binding in collect_env_bindings()}
    assert "TEST_DB_BACKEND" in names


def test_collect_env_bindings_exposes_raes_runtime_keys_without_retired_selector():
    names = {binding.name for binding in collect_env_bindings()}
    cutover_keys = {
        "RAES_OPERATION_RECORD_PRUNE_BATCH_SIZE",
        "RAES_OPERATION_RECORD_PRUNE_INTERVAL_SECONDS",
        "RAES_OPERATION_RECORD_RETENTION_DAYS",
        "SHIFTER_RAES_CONTENT_DELIVERY_MAX_PAYLOAD_BYTES",
        "SHIFTER_RAES_CONTENT_DELIVERY_PREFIX",
        "SHIFTER_RAES_PACKAGE_BUCKET",
        "SHIFTER_RAES_PACKAGE_MAX_ARCHIVE_BYTES",
        "SHIFTER_RAES_PACKAGE_MAX_ENTRIES",
        "SHIFTER_RAES_PACKAGE_MAX_UNCOMPRESSED_BYTES",
        "SHIFTER_RAES_PACKAGE_PREFIX",
        "SHIFTER_RAES_PACKAGE_ROOT",
    }
    assert cutover_keys <= names
    assert "SHIFTER_RAES_NATIVE_PROVISIONING" not in names
    for expected in cutover_keys:
        suffix = expected.split("RAES", maxsplit=1)[1]
        assert {name for name in names if name.endswith(suffix)} == {expected}


def test_env_manifest_is_current():
    assert manifest_is_current(), (
        "config/env-manifest.json is stale; run `python manage.py generate_env_manifest` from shifter_platform"
    )
