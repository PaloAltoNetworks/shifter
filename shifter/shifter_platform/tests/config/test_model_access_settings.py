"""Runtime composition loads model-access only from the mounted artifact."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured

from config._model_access_settings import load_model_access_catalog
from shared.model_access import seal_catalog

EXAMPLE = Path(__file__).parents[4] / "docs/architecture/model-access/example-policy.v1.json"
DIGEST = "sha256:e519d0e2ad1469657a5387d012071e9fe65b8d478a90d870a5a0a91c418c444b"


def test_runtime_reparses_mounted_catalog_and_expected_digest():
    catalog = load_model_access_catalog(enabled=False, path=str(EXAMPLE), expected_digest=DIGEST)
    assert catalog is not None
    assert catalog.digest == DIGEST


def test_enabled_runtime_requires_path_and_digest():
    with pytest.raises(ImproperlyConfigured, match="requires"):
        load_model_access_catalog(enabled=True, path="", expected_digest="")


def test_enabled_runtime_rejects_catalog_declared_disabled():
    with pytest.raises(ImproperlyConfigured, match="catalog declared disabled"):
        load_model_access_catalog(enabled=True, path=str(EXAMPLE), expected_digest=DIGEST)


def test_enabled_runtime_accepts_catalog_declared_enabled(tmp_path):
    payload = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    payload.pop("digest")
    payload["enabled"] = True
    catalog = seal_catalog(payload)
    path = tmp_path / "enabled-catalog.json"
    path.write_text(catalog.model_dump_json(), encoding="utf-8")

    loaded = load_model_access_catalog(enabled=True, path=str(path), expected_digest=catalog.digest)

    assert loaded == catalog


def test_expected_digest_mismatch_fails_closed_without_catalog_content():
    with pytest.raises(ImproperlyConfigured) as exc:
        load_model_access_catalog(enabled=False, path=str(EXAMPLE), expected_digest="sha256:" + "f" * 64)
    assert "vertex-primary" not in str(exc.value)


def test_disabled_runtime_without_staged_artifact_is_inert():
    assert load_model_access_catalog(enabled=False, path="", expected_digest="") is None


def test_catalog_file_size_is_bounded(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_bytes(b" " * (2 * 1024 * 1024 + 1))
    with pytest.raises(ImproperlyConfigured, match="size"):
        load_model_access_catalog(enabled=False, path=str(path), expected_digest=DIGEST)
