"""Fail-closed composition-root tests for native CTF content settings."""

from __future__ import annotations

import importlib
import json
import os

import pytest
from django.core.exceptions import ImproperlyConfigured

MODULE = "config._ctf_content_settings"
ENV_KEYS = (
    "SHIFTER_CTF_CONTENT_BUCKET",
    "SHIFTER_CTF_CONTENT_MAX_BYTES",
    "SHIFTER_CTF_CONTENT_PREFIX",
    "SHIFTER_CTF_CONTENT_REFERENCES_JSON",
)


def _reload(monkeypatch, **env):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return importlib.reload(importlib.import_module(MODULE))


@pytest.fixture(autouse=True)
def _restore_module():
    yield
    for key in ENV_KEYS:
        os.environ.pop(key, None)
    importlib.reload(importlib.import_module(MODULE))


def _references() -> str:
    return json.dumps(
        {
            "contract": "shifter-ctf-content-references/v1",
            "references": [
                {
                    "scenario_id": "scenario-one",
                    "object_key": "ctf/content-bundles/aa/bundle.json",
                    "digest": f"sha256:{'a' * 64}",
                }
            ],
        }
    )


def test_absent_references_are_inert(monkeypatch) -> None:
    module = _reload(monkeypatch)
    assert module.CTF_CONTENT_REFERENCES.references == {}


def test_references_require_explicit_bucket(monkeypatch) -> None:
    references = _references()
    with pytest.raises(ImproperlyConfigured, match="BUCKET"):
        _reload(monkeypatch, SHIFTER_CTF_CONTENT_REFERENCES_JSON=references)


def test_declared_reference_and_bucket_parse(monkeypatch) -> None:
    module = _reload(
        monkeypatch,
        SHIFTER_CTF_CONTENT_BUCKET="private-content",
        SHIFTER_CTF_CONTENT_REFERENCES_JSON=_references(),
    )
    assert module.CTF_CONTENT_REFERENCES.get("scenario-one") is not None


@pytest.mark.parametrize("value", ["0", "not-an-int", str(8 * 1024 * 1024 + 1)])
def test_invalid_size_limit_fails_startup(monkeypatch, value: str) -> None:
    with pytest.raises(ImproperlyConfigured):
        _reload(monkeypatch, SHIFTER_CTF_CONTENT_MAX_BYTES=value)
