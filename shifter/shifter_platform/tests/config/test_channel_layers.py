"""Tests for the Django Channels CHANNEL_LAYERS configuration helper.

Covers the Redis AUTH/TLS contract from ADR-008-R6 (#963): the helper picks
the right backend for local dev, plaintext-Redis, and TLS-with-password
postures, and fails closed when TLS is enabled without a password.

Also covers the explicit channel-layer backend posture from ADR-018 (#849):
``CHANNEL_LAYER_BACKEND`` selects the backend independently of the portal
``enable_autoscaling`` topology, fails closed when ``redis`` is requested
without ``REDIS_HOST``, and exposes a non-secret startup posture for logging.
"""

from __future__ import annotations

import logging

import pytest
from django.core.exceptions import ImproperlyConfigured

from config._channels import (
    describe_channel_layer_posture,
    log_channel_layer_posture,
)
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


# ---------------------------------------------------------------------------
# Explicit channel-layer backend posture (ADR-018, #849)
#
# CHANNEL_LAYER_BACKEND decouples the runtime backend from the portal
# enable_autoscaling topology. A deployed `redis` posture fails closed when
# REDIS_HOST is absent instead of silently degrading to InMemoryChannelLayer.
# ---------------------------------------------------------------------------


def test_explicit_redis_backend_builds_redis_layer():
    """CHANNEL_LAYER_BACKEND=redis with REDIS_HOST set builds the Redis layer
    (same tuple form as the host-presence heuristic)."""
    layers = _build_channel_layers(
        {
            "CHANNEL_LAYER_BACKEND": "redis",
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


def test_explicit_redis_backend_fails_closed_without_host():
    """The failure mode #849 exists to close: a deployed `redis` posture with
    no REDIS_HOST must raise, never fall back to InMemoryChannelLayer."""
    with pytest.raises(ImproperlyConfigured, match="REDIS_HOST"):
        _build_channel_layers({"CHANNEL_LAYER_BACKEND": "redis"})


def test_explicit_redis_backend_fails_closed_with_blank_host():
    """Blank REDIS_HOST is the same failure mode as missing."""
    with pytest.raises(ImproperlyConfigured, match="REDIS_HOST"):
        _build_channel_layers({"CHANNEL_LAYER_BACKEND": "redis", "REDIS_HOST": "  "})


def test_explicit_in_memory_backend_ignores_present_redis_host():
    """CHANNEL_LAYER_BACKEND=in_memory forces the in-memory layer even when a
    stray REDIS_HOST is present (deliberate cost-saving / non-event posture).
    The drift stays observable via the startup posture, not via behavior."""
    layers = _build_channel_layers(
        {
            "CHANNEL_LAYER_BACKEND": "in_memory",
            "REDIS_HOST": "10.0.0.20",
        }
    )

    assert layers == {
        "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
    }


@pytest.mark.parametrize("backend_value", ["REDIS", "Redis", "in_memory", "IN_MEMORY", "In_Memory"])
def test_backend_value_is_case_insensitive(backend_value):
    """CHANNEL_LAYER_BACKEND parsing matches the rest of the env contract:
    case-insensitive, surrounding whitespace stripped."""
    layers = _build_channel_layers(
        {
            "CHANNEL_LAYER_BACKEND": f"  {backend_value}  ",
            "REDIS_HOST": "10.0.0.20",
        }
    )

    if backend_value.lower() == "redis":
        assert layers["default"]["BACKEND"] == "channels_redis.core.RedisChannelLayer"
    else:
        assert layers["default"]["BACKEND"] == "channels.layers.InMemoryChannelLayer"


def test_unknown_backend_value_fails_closed():
    """An unrecognised CHANNEL_LAYER_BACKEND is a configuration error, not a
    silent fall-through to a default backend."""
    with pytest.raises(ImproperlyConfigured, match="CHANNEL_LAYER_BACKEND"):
        _build_channel_layers({"CHANNEL_LAYER_BACKEND": "memcached", "REDIS_HOST": "10.0.0.20"})


def test_unset_backend_preserves_host_presence_heuristic():
    """When CHANNEL_LAYER_BACKEND is unset (local dev / pytest), the legacy
    REDIS_HOST-presence heuristic still decides — no behavior change for
    environments that do not opt into the explicit posture."""
    assert _build_channel_layers({})["default"]["BACKEND"] == "channels.layers.InMemoryChannelLayer"
    assert (
        _build_channel_layers({"REDIS_HOST": "10.0.0.20"})["default"]["BACKEND"]
        == "channels_redis.core.RedisChannelLayer"
    )


# ---------------------------------------------------------------------------
# Startup posture observability (#849 AC2)
# ---------------------------------------------------------------------------


def test_describe_posture_reports_explicit_redis_fields():
    posture = describe_channel_layer_posture(
        {
            "CHANNEL_LAYER_BACKEND": "redis",
            "REDIS_HOST": "10.0.0.20",
            "REDIS_PORT": "6380",
            "REDIS_TLS": "true",
        }
    )

    assert posture == {
        "backend": "redis",
        "explicit_backend": "redis",
        "redis_host_present": True,
        "redis_port": 6380,
        "redis_tls": True,
    }


def test_describe_posture_reports_unset_in_memory_fields():
    posture = describe_channel_layer_posture({})

    assert posture == {
        "backend": "in_memory",
        "explicit_backend": None,
        "redis_host_present": False,
        "redis_port": None,
        "redis_tls": False,
    }


def test_describe_posture_surfaces_in_memory_over_present_host_drift():
    """in_memory backend with a present REDIS_HOST is the deliberate-but-must-
    not-be-silent case: the posture reports both so the drift is visible."""
    posture = describe_channel_layer_posture({"CHANNEL_LAYER_BACKEND": "in_memory", "REDIS_HOST": "10.0.0.20"})

    assert posture["backend"] == "in_memory"
    assert posture["redis_host_present"] is True


def test_log_posture_emits_single_non_secret_record(caplog):
    """The startup posture log makes the active backend observable in deployed
    environments without leaking the password, CA, or even the hostname.

    A propagating test logger is injected because the production ``config``
    logger sets ``propagate: False`` (see ``config/_logging_config.py``), which
    pytest's root-attached ``caplog`` handler cannot observe."""
    test_logger = logging.getLogger("tests.channel_layer_posture")
    with caplog.at_level(logging.INFO, logger=test_logger.name):
        log_channel_layer_posture(
            {
                "CHANNEL_LAYER_BACKEND": "redis",
                "REDIS_HOST": "10.0.0.20",
                "REDIS_PORT": "6380",
                "REDIS_TLS": "true",
                "REDIS_PASSWORD": "supersecretauthtoken",  # NOSONAR - test fixture, not a real credential
                "REDIS_CA_PEM": "-----BEGIN CERTIFICATE-----\nMIIBfake==\n-----END CERTIFICATE-----\n",
            },
            logger=test_logger,
        )

    records = [r for r in caplog.records if "channel-layer" in r.getMessage()]
    assert len(records) == 1
    message = records[0].getMessage()
    assert "backend=redis" in message
    assert "redis_tls=True" in message
    # No secrets / sensitive topology in the emitted line.
    assert "supersecretauthtoken" not in message
    assert "BEGIN CERTIFICATE" not in message
    assert "10.0.0.20" not in message
