"""Tests for optional per-instance agent asset helpers."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_agent_presigned_url_returns_none_without_agent() -> None:
    from agent_assets import get_agent_presigned_url

    assert get_agent_presigned_url({}) is None


def test_agent_presigned_url_returns_none_without_bucket(monkeypatch) -> None:
    from agent_assets import get_agent_presigned_url

    monkeypatch.delenv("AGENT_STORAGE_BUCKET", raising=False)
    monkeypatch.delenv("AGENT_S3_BUCKET", raising=False)

    assert get_agent_presigned_url({"agent": {"s3_key": "agents/xdr.deb"}}) is None


def test_agent_presigned_url_uses_configured_storage_bucket(monkeypatch) -> None:
    from agent_assets import get_agent_presigned_url

    class Storage:
        def generate_presigned_download_url(self, *, bucket: str, key: str, expires_in: int) -> str:
            assert bucket == "agent-assets"
            assert key == "agents/xdr.deb"
            assert expires_in == 3600
            return "https://signed.example/agents/xdr.deb"

    cloud = ModuleType("cloud")
    cloud.get_object_storage = lambda: Storage()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "cloud", cloud)
    monkeypatch.setenv("AGENT_STORAGE_BUCKET", "agent-assets")

    result = get_agent_presigned_url({"agent": {"s3_key": "agents/xdr.deb"}})

    assert result == "https://signed.example/agents/xdr.deb"


def test_agent_presigned_url_falls_back_to_legacy_bucket_name(monkeypatch) -> None:
    from agent_assets import get_agent_presigned_url

    class Storage:
        def generate_presigned_download_url(self, *, bucket: str, key: str, expires_in: int) -> str:
            return f"{bucket}/{key}/{expires_in}"

    cloud = ModuleType("cloud")
    cloud.get_object_storage = lambda: Storage()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "cloud", cloud)
    monkeypatch.delenv("AGENT_STORAGE_BUCKET", raising=False)
    monkeypatch.setenv("AGENT_S3_BUCKET", "legacy-assets")

    result = get_agent_presigned_url({"agent": {"s3_key": "agents/xdr.deb"}})

    assert result == "legacy-assets/agents/xdr.deb/3600"


def test_agent_presigned_url_returns_none_when_storage_errors(monkeypatch) -> None:
    from agent_assets import get_agent_presigned_url

    def raise_storage_error() -> object:
        raise RuntimeError("storage unavailable")

    cloud = ModuleType("cloud")
    cloud.get_object_storage = raise_storage_error  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "cloud", cloud)
    monkeypatch.setenv("AGENT_STORAGE_BUCKET", "agent-assets")

    assert get_agent_presigned_url({"agent": {"s3_key": "agents/xdr.deb"}}) is None


def _install_storage(monkeypatch, storage) -> None:
    cloud = ModuleType("cloud")
    cloud.get_object_storage = lambda: storage  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "cloud", cloud)


def test_polaris_tests_presigned_url_mints_generation_bound_short_url(monkeypatch) -> None:
    from agent_assets import get_polaris_tests_presigned_url

    calls: dict[str, object] = {}

    class Storage:
        def head_object(self, bucket: str, key: str) -> dict[str, object]:
            calls["head"] = (bucket, key)
            return {"content_length": 10, "etag": "e", "generation": 99}

        def generate_presigned_download_url(self, *, bucket: str, key: str, expires_in: int, object_version) -> str:
            calls["sign"] = (bucket, key, expires_in, object_version)
            return "https://storage.googleapis.com/assets/polaris?X-Goog-Signature=sig"

    _install_storage(monkeypatch, Storage())
    monkeypatch.delenv("POLARIS_TESTS_BUCKET", raising=False)
    monkeypatch.delenv("POLARIS_TESTS_KEY", raising=False)
    monkeypatch.setenv("AGENT_STORAGE_BUCKET", "assets-bucket")

    url = get_polaris_tests_presigned_url()

    assert url == "https://storage.googleapis.com/assets/polaris?X-Goog-Signature=sig"
    # Exact object, version-bound (as an opaque string), short (900s) expiry.
    assert calls["head"] == ("assets-bucket", "polaris/tests/polaris-tests.tar.gz")
    assert calls["sign"] == ("assets-bucket", "polaris/tests/polaris-tests.tar.gz", 900, "99")


def test_polaris_tests_presigned_url_honors_explicit_bucket_and_key(monkeypatch) -> None:
    from agent_assets import get_polaris_tests_presigned_url

    class Storage:
        def head_object(self, bucket: str, key: str) -> dict[str, object]:
            return {"generation": 7}

        def generate_presigned_download_url(self, *, bucket: str, key: str, expires_in: int, object_version) -> str:
            return f"{bucket}/{key}"

    _install_storage(monkeypatch, Storage())
    monkeypatch.setenv("POLARIS_TESTS_BUCKET", "custom-tests")
    monkeypatch.setenv("POLARIS_TESTS_KEY", "custom/tests.tar.gz")

    assert get_polaris_tests_presigned_url() == "custom-tests/custom/tests.tar.gz"


def test_polaris_tests_presigned_url_requires_bucket(monkeypatch) -> None:
    from agent_assets import get_polaris_tests_presigned_url

    monkeypatch.delenv("POLARIS_TESTS_BUCKET", raising=False)
    monkeypatch.delenv("AGENT_STORAGE_BUCKET", raising=False)
    monkeypatch.delenv("AGENT_S3_BUCKET", raising=False)

    with pytest.raises(ValueError, match="POLARIS_TESTS_BUCKET"):
        get_polaris_tests_presigned_url()


def test_polaris_tests_presigned_url_fails_closed_on_storage_error(monkeypatch) -> None:
    from agent_assets import get_polaris_tests_presigned_url
    from cloud.exceptions import CloudStorageError

    class Storage:
        def head_object(self, bucket: str, key: str) -> dict[str, object]:
            raise CloudStorageError("object not found")

        def generate_presigned_download_url(self, **_kwargs: object) -> str:
            raise AssertionError("must not sign an unsigned/unbound fallback when head fails")

    _install_storage(monkeypatch, Storage())
    monkeypatch.setenv("AGENT_STORAGE_BUCKET", "assets-bucket")

    with pytest.raises(CloudStorageError):
        get_polaris_tests_presigned_url()
