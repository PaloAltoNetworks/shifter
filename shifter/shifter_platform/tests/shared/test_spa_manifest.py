"""Tests for the Vite build-manifest resolver used by SPA host views (#1302).

Exercises the real resolver against an on-disk manifest and Django ``static()``
(observable behavior) rather than mocking first-party seams.
"""

from __future__ import annotations

import json

import pytest

from shared import spa

PLAIN_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@pytest.fixture
def static_root(tmp_path, settings):
    """Point STATICFILES_DIRS at a temp dir and use non-manifest static storage."""
    settings.STATICFILES_DIRS = [tmp_path]
    settings.STORAGES = PLAIN_STORAGES
    settings.DEBUG = True  # bypass the process-lifetime manifest cache
    return tmp_path


def _write_manifest(root, payload):
    manifest_dir = root / "spa" / ".vite"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")


def test_resolves_entry_js_and_css(static_root):
    _write_manifest(
        static_root,
        {"src/main.tsx": {"file": "assets/main-abc.js", "css": ["assets/main-abc.css"], "isEntry": True}},
    )
    result = spa.vite_asset_urls()
    assert result["js"].endswith("spa/assets/main-abc.js")
    assert len(result["css"]) == 1
    assert result["css"][0].endswith("spa/assets/main-abc.css")


def test_entry_without_css(static_root):
    _write_manifest(static_root, {"src/main.tsx": {"file": "assets/main-abc.js"}})
    result = spa.vite_asset_urls()
    assert result["js"].endswith("spa/assets/main-abc.js")
    assert result["css"] == []


def test_missing_manifest_returns_empty(static_root):
    # No manifest written under static_root.
    result = spa.vite_asset_urls()
    assert result["js"] is None
    assert result["css"] == []
