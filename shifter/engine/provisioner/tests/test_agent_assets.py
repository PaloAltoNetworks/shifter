"""Tests for optional per-instance agent asset helpers."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

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
