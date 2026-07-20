"""Tests for the bounded TTL credential cache in engine.secrets (#929).

A per-range connect storm should collapse to one Secrets Manager fetch per
secret reference for the TTL window. The cache is keyed by secret reference
(never by value), TTL-bounded, size-bounded, and clearable.

The cache unit is driven through its public clock seam (no internal patching);
the integration behavior (``get_ssh_key``/``get_rdp_password`` collapsing repeat
reads) is proven at the boto3 Secrets Manager boundary.
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _fresh_module_cache():
    from engine.secrets import clear_secret_cache

    clear_secret_cache()
    yield
    clear_secret_cache()


def _aws_secrets_client(value="TEST-SSH-PRIVATE-KEY-MATERIAL"):  # nosec B107
    client = MagicMock()
    client.get_secret_value.return_value = {"SecretString": value}
    return client


class TestSecretCacheUnit:
    """Drive the cache via its injected clock — deterministic, no patching."""

    def test_hit_within_ttl_returns_value(self):
        from engine.secrets import _SecretCache

        now = {"t": 100.0}
        cache = _SecretCache(clock=lambda: now["t"])
        cache.set("ref", "secret", ttl=10, max_entries=8)

        now["t"] = 105.0
        assert cache.get("ref", ttl=10) == "secret"

    def test_entry_expires_after_ttl(self):
        from engine.secrets import _SecretCache

        now = {"t": 100.0}
        cache = _SecretCache(clock=lambda: now["t"])
        cache.set("ref", "secret", ttl=10, max_entries=8)

        now["t"] = 111.0  # past expiry
        assert cache.get("ref", ttl=10) is None

    def test_ttl_zero_never_stores_or_returns(self):
        from engine.secrets import _SecretCache

        cache = _SecretCache(clock=lambda: 0.0)
        cache.set("ref", "secret", ttl=0, max_entries=8)
        assert cache.get("ref", ttl=0) is None

    def test_bounded_eviction_drops_oldest(self):
        from engine.secrets import _SecretCache

        now = {"t": 0.0}
        cache = _SecretCache(clock=lambda: now["t"])
        cache.set("ref-1", "a", ttl=100, max_entries=2)
        now["t"] = 1.0
        cache.set("ref-2", "b", ttl=100, max_entries=2)
        now["t"] = 2.0
        cache.set("ref-3", "c", ttl=100, max_entries=2)  # evicts ref-1 (oldest)

        assert cache.get("ref-1", ttl=100) is None
        assert cache.get("ref-2", ttl=100) == "b"
        assert cache.get("ref-3", ttl=100) == "c"

    def test_clear_empties_cache(self):
        from engine.secrets import _SecretCache

        cache = _SecretCache(clock=lambda: 0.0)
        cache.set("ref", "secret", ttl=100, max_entries=8)
        cache.clear()
        assert cache.get("ref", ttl=100) is None


class TestSecretHelperCaching:
    """Prove repeat reads collapse to one provider fetch at the boto3 boundary."""

    def test_repeated_fetch_same_ref_hits_provider_once(self, settings):
        from engine.secrets import get_ssh_key

        settings.CLOUD_PROVIDER = "aws"
        settings.SECRET_CACHE_TTL_SECONDS = 300
        ref = "arn:aws:secretsmanager:us-east-2:1:secret:range-1-ssh"

        client = _aws_secrets_client()
        with patch("boto3.client", return_value=client):
            assert get_ssh_key(ref) == "TEST-SSH-PRIVATE-KEY-MATERIAL"
            assert get_ssh_key(ref) == "TEST-SSH-PRIVATE-KEY-MATERIAL"

        client.get_secret_value.assert_called_once_with(SecretId=ref)

    def test_distinct_refs_each_fetch(self, settings):
        from engine.secrets import get_rdp_password, get_ssh_key

        settings.CLOUD_PROVIDER = "aws"
        settings.SECRET_CACHE_TTL_SECONDS = 300

        client = _aws_secrets_client()
        with patch("boto3.client", return_value=client):
            get_ssh_key("ref-a")
            get_rdp_password("ref-b")

        assert client.get_secret_value.call_count == 2

    def test_disabled_cache_fetches_every_time(self, settings):
        from engine.secrets import get_ssh_key

        settings.CLOUD_PROVIDER = "aws"
        settings.SECRET_CACHE_TTL_SECONDS = 0
        ref = "ref-disabled"

        client = _aws_secrets_client()
        with patch("boto3.client", return_value=client):
            get_ssh_key(ref)
            get_ssh_key(ref)

        assert client.get_secret_value.call_count == 2

    def test_failed_fetch_is_not_cached(self, settings):
        from botocore.exceptions import ClientError

        from engine.secrets import SecretsError, get_ssh_key

        settings.CLOUD_PROVIDER = "aws"
        settings.SECRET_CACHE_TTL_SECONDS = 300

        client = MagicMock()
        client.get_secret_value.side_effect = [
            ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "GetSecretValue"),
            {"SecretString": "recovered"},
        ]
        with patch("boto3.client", return_value=client):
            with pytest.raises(SecretsError):
                get_ssh_key("ref-flaky")
            assert get_ssh_key("ref-flaky") == "recovered"

        assert client.get_secret_value.call_count == 2
