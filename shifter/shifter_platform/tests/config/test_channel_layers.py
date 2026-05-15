"""Tests for the Django Channels CHANNEL_LAYERS configuration helper.

Covers the Redis AUTH/TLS contract from ADR-008-R6 (#963): the helper picks
the right backend for local dev, plaintext-Redis, and TLS-with-password
postures, and fails closed when TLS is enabled without a password.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured

from config.settings import _build_channel_layers


def test_returns_in_memory_layer_when_redis_host_unset():
    """Local-dev fallback: no REDIS_HOST → InMemoryChannelLayer. Preserves
    the pre-#963 ergonomics for `manage.py runserver` outside a container."""
    layers = _build_channel_layers({})

    assert layers == {
        "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
    }


def test_returns_in_memory_layer_when_redis_host_blank():
    """Treat blank REDIS_HOST as 'unset' — mirrors os.environ.get default
    when an env var is exported empty."""
    layers = _build_channel_layers({"REDIS_HOST": "  "})

    assert layers["default"]["BACKEND"] == "channels.layers.InMemoryChannelLayer"


def test_returns_tuple_form_when_tls_disabled():
    """Plaintext Redis (local docker-compose, AWS pre-#963 posture): tuple
    host form, no password embedded anywhere."""
    layers = _build_channel_layers(
        {
            "REDIS_HOST": "10.0.0.20",
            "REDIS_PORT": "6379",
        }
    )

    assert layers == {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [("10.0.0.20", 6379)]},
        },
    }


def test_fails_closed_when_tls_enabled_without_ca():
    """ADR-008-R6 fail-closed: REDIS_TLS=true without REDIS_CA_PEM must raise.
    Memorystore uses a private CA, so silently falling back to the system
    trust store would never validate the server cert anyway — surface the
    misconfiguration at startup, same shape as the missing-password path."""
    with pytest.raises(ImproperlyConfigured, match="REDIS_CA_PEM"):
        _build_channel_layers(
            {
                "REDIS_HOST": "10.0.0.20",
                "REDIS_PORT": "6378",
                "REDIS_TLS": "true",
                "REDIS_PASSWORD": "test-auth-token",  # NOSONAR - test fixture, not a real credential
                # REDIS_CA_PEM deliberately absent
            }
        )


def test_fails_closed_when_tls_enabled_with_blank_ca():
    """Whitespace-only REDIS_CA_PEM is the same failure mode as missing."""
    with pytest.raises(ImproperlyConfigured, match="REDIS_CA_PEM"):
        _build_channel_layers(
            {
                "REDIS_HOST": "10.0.0.20",
                "REDIS_PORT": "6378",
                "REDIS_TLS": "true",
                "REDIS_PASSWORD": "test-auth-token",  # NOSONAR - test fixture, not a real credential
                "REDIS_CA_PEM": "   \n  \n",
            }
        )


def test_returns_rediss_with_ssl_ca_data_when_ca_present():
    """Secure-posture happy path for GCP Memorystore: REDIS_TLS=true,
    REDIS_PASSWORD, and a REDIS_CA_PEM (the Memorystore server CA from
    Secret Manager) produce a dict-form channels_redis host carrying
    address + ssl_cert_reqs=required + ssl_ca_data=<PEM>.

    channels_redis.utils.create_pool unpacks the dict into
    `aioredis.ConnectionPool.from_url(address, **rest)`, so redis-py's
    SSL kwargs flow through and the server certificate is verified
    against the Memorystore CA rather than the system trust store."""
    ca_pem = "-----BEGIN CERTIFICATE-----\nMIIBfakeMemorystoreCAcertificateForTesting==\n-----END CERTIFICATE-----\n"
    layers = _build_channel_layers(
        {
            "REDIS_HOST": "10.0.0.20",
            "REDIS_PORT": "6378",
            "REDIS_TLS": "true",
            "REDIS_PASSWORD": "test-auth-token",  # NOSONAR - test fixture, not a real credential
            "REDIS_CA_PEM": ca_pem,
        }
    )

    host_entry = layers["default"]["CONFIG"]["hosts"][0]
    assert host_entry == {
        "address": "rediss://:test-auth-token@10.0.0.20:6378/0",
        "ssl_cert_reqs": "required",
        "ssl_ca_data": ca_pem,
    }


def test_password_is_not_embedded_when_tls_disabled():
    """Defense in depth: even if REDIS_PASSWORD is set, when REDIS_TLS is
    not 'true' we MUST NOT silently embed the password in a plaintext URL.
    The tuple form is used; the password is ignored."""
    layers = _build_channel_layers(
        {
            "REDIS_HOST": "10.0.0.20",
            "REDIS_PORT": "6379",
            "REDIS_PASSWORD": "test-auth-token",  # NOSONAR - test fixture, not a real credential
            # REDIS_TLS deliberately unset
        }
    )

    config = layers["default"]["CONFIG"]
    assert config["hosts"] == [("10.0.0.20", 6379)]
    # And no URL form snuck through.
    for host in config["hosts"]:
        assert not isinstance(host, str) or "test-auth-token" not in host


def test_fails_closed_when_tls_enabled_without_password():
    """ADR-008-R6 fail-closed: REDIS_TLS=true without REDIS_PASSWORD must
    raise — silently downgrading to plaintext is the failure mode the
    preflight calls out."""
    with pytest.raises(ImproperlyConfigured, match="REDIS_PASSWORD"):
        _build_channel_layers(
            {
                "REDIS_HOST": "10.0.0.20",
                "REDIS_PORT": "6379",
                "REDIS_TLS": "true",
                # REDIS_PASSWORD deliberately empty
            }
        )


def test_fails_closed_when_tls_enabled_with_blank_password():
    """Blank password is the same failure mode as missing password."""
    with pytest.raises(ImproperlyConfigured, match="REDIS_PASSWORD"):
        _build_channel_layers(
            {
                "REDIS_HOST": "10.0.0.20",
                "REDIS_PORT": "6379",
                "REDIS_TLS": "true",
                "REDIS_PASSWORD": "   ",
            }
        )


def test_redis_port_default_when_unset():
    """When REDIS_PORT is absent, default to 6379 (matches the existing
    pre-#963 behavior)."""
    layers = _build_channel_layers({"REDIS_HOST": "10.0.0.20"})

    assert layers["default"]["CONFIG"]["hosts"] == [("10.0.0.20", 6379)]


@pytest.mark.parametrize("tls_value", ["TRUE", "True", "true"])
def test_tls_flag_accepts_case_insensitive_true(tls_value):
    """REDIS_TLS parsing matches the rest of the renderer's _env_bool
    convention: case-insensitive 'true'."""
    ca_pem = "-----BEGIN CERTIFICATE-----\nMIIBfakeMemorystoreCAcertificateForTesting==\n-----END CERTIFICATE-----\n"
    layers = _build_channel_layers(
        {
            "REDIS_HOST": "10.0.0.20",
            "REDIS_PORT": "6378",
            "REDIS_TLS": tls_value,
            "REDIS_PASSWORD": "tok",
            "REDIS_CA_PEM": ca_pem,
        }
    )

    hosts = layers["default"]["CONFIG"]["hosts"]
    assert hosts[0]["address"] == "rediss://:tok@10.0.0.20:6378/0"
    assert hosts[0]["ssl_cert_reqs"] == "required"
    assert hosts[0]["ssl_ca_data"] == ca_pem


@pytest.mark.parametrize("tls_value", ["false", "False", "0", "", "no", "anything-else"])
def test_tls_flag_anything_else_is_disabled(tls_value):
    """Conservative parsing: only the exact case-insensitive string 'true'
    flips the secure posture. Everything else stays plaintext."""
    layers = _build_channel_layers(
        {
            "REDIS_HOST": "10.0.0.20",
            "REDIS_PORT": "6379",
            "REDIS_TLS": tls_value,
        }
    )

    assert layers["default"]["CONFIG"]["hosts"] == [("10.0.0.20", 6379)]
