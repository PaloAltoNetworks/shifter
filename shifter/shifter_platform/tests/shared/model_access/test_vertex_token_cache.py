"""Bounded, single-flight, early-expiry reuse of impersonated Vertex tokens (#2124).

Tokens are cached only in broker memory, keyed by the complete approved target,
and refreshed once per key. A stored-credential revision keys a new entry so a
rotated credential never reuses a fenced token.
"""

import threading

import pytest

from model_broker import provider_credentials
from model_broker.provider_credentials import _AccessTokenCache, _vertex_headers
from shared.model_access.provider_runtime import ProviderTarget


def _target(*, principal="model-invoke@models-a.iam.gserviceaccount.com", credential_reference="impersonate:v1"):
    return ProviderTarget(
        shard_id="vertex-primary",
        provider="vertex-v1",
        region="europe-west4",
        count_region="eu",
        model="publishers/anthropic/models/claude-sonnet",
        credential_reference=credential_reference,
        project="models-a",
        principal=principal,
        context_window_tokens=200_000,
    )


def test_cache_reuses_a_live_token_and_refreshes_after_early_expiry():
    cache = _AccessTokenCache(early_expiry_seconds=60.0)
    calls = []

    def mint_live():
        calls.append("live")
        return "token-live", 3600.0

    assert cache.token(("k",), mint_live) == "token-live"
    assert cache.token(("k",), mint_live) == "token-live"
    assert calls == ["live"]  # a live token is reused without a second mint

    expiring = []

    def mint_expiring():
        expiring.append("expiring")
        return f"token-{len(expiring)}", 0.0  # already inside the early-expiry margin

    assert cache.token(("e",), mint_expiring) == "token-1"
    assert cache.token(("e",), mint_expiring) == "token-2"  # never treated as fresh, always re-minted
    assert expiring == ["expiring", "expiring"]


def test_cache_mints_once_under_concurrent_single_flight():
    cache = _AccessTokenCache(early_expiry_seconds=60.0)
    started = threading.Event()
    release = threading.Event()
    calls = []

    def mint():
        calls.append("mint")
        started.set()
        release.wait(2)
        return "token-shared", 3600.0

    results = []

    def worker():
        results.append(cache.token(("shared",), mint))

    threads = [threading.Thread(target=worker) for _ in range(5)]
    threads[0].start()
    assert started.wait(2)  # first caller is inside mint holding the single-flight lock
    for thread in threads[1:]:
        thread.start()
    release.set()
    for thread in threads:
        thread.join(3)

    assert calls == ["mint"]  # exactly one mint served every concurrent caller
    assert results == ["token-shared"] * 5


def test_vertex_headers_reuse_one_mint_per_target_and_key_by_revision(monkeypatch):
    provider_credentials._VERTEX_TOKENS = _AccessTokenCache(early_expiry_seconds=60.0)
    minted = []

    def fake_mint(target, stored):
        minted.append(target.credential_reference)
        return f"tok-{len(minted)}", 3600.0

    monkeypatch.setattr(provider_credentials, "_mint_vertex_token", fake_mint)

    first = _vertex_headers(_target(credential_reference="impersonate:v1"))
    again = _vertex_headers(_target(credential_reference="impersonate:v1"))
    assert first == again
    assert first["authorization"] == "Bearer tok-1"
    assert first["accept-encoding"] == "identity"
    assert minted == ["impersonate:v1"]  # one mint reused for the same approved target

    rotated = _vertex_headers(_target(credential_reference="impersonate:v2"))
    assert rotated["authorization"] == "Bearer tok-2"  # a revision change keys a fresh token
    assert minted == ["impersonate:v1", "impersonate:v2"]


def _synthetic_private_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


def test_stored_vertex_credential_mismatch_is_rejected_before_any_mint(monkeypatch):
    from shared.model_access.source_credentials import GoogleKeyCredential

    provider_credentials._VERTEX_TOKENS = _AccessTokenCache()
    monkeypatch.setattr(
        provider_credentials, "_mint_vertex_token", lambda *a, **k: pytest.fail("minted despite target mismatch")
    )
    stored = GoogleKeyCredential(
        type="service_account",
        project_id="other-project",
        client_email="model-invoke@other-project.iam.gserviceaccount.com",
        private_key_id="k1",
        private_key=_synthetic_private_key(),
        token_uri="https://oauth2.googleapis.com/token",
    )
    with pytest.raises(Exception, match="target_mismatch"):
        _vertex_headers(_target(), stored=stored)
