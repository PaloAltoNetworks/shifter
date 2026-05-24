"""Django Channels (Redis) layer configuration.

Extracted from ``config/settings.py`` to keep that module under the
500-line cap (Sonar S104). Pure functions live here; the module is
imported by ``config.settings`` to populate the ``CHANNEL_LAYERS``
setting.

Three runtime postures, in order of preference, derived from the env:
    1. REDIS_HOST empty       -> InMemoryChannelLayer (local dev,
                                 pytest runs without a Redis dependency).
    2. REDIS_HOST set, no TLS -> channels_redis tuple host form (plaintext
                                 Redis on a private network — the AWS and
                                 pre-#963 GCP shape).
    3. REDIS_HOST + REDIS_TLS -> rediss://<password>@host:port/0 URL host.
                                 REDIS_PASSWORD is hydrated by entrypoint.sh
                                 from Secret Manager (ADR-008-R6).

Fail closed when the TLS flag is on but no password was hydrated — silent
fallback to plaintext is the failure mode #963 was opened to close.
"""

from __future__ import annotations

from collections.abc import Mapping

__all__ = ["_build_channel_layers"]


def _build_channel_layers(env: Mapping[str, str]) -> dict[str, dict[str, object]]:
    """Build CHANNEL_LAYERS from the given mapping (typically os.environ).

    Pure function so it is unit-testable without touching real settings.
    """
    from django.core.exceptions import ImproperlyConfigured

    host = env.get("REDIS_HOST", "").strip()
    if not host:
        return {
            "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
        }

    port = int(env.get("REDIS_PORT", "6379"))
    tls = env.get("REDIS_TLS", "").strip().lower() == "true"
    if tls:
        password = env.get("REDIS_PASSWORD", "").strip()
        if not password:
            raise ImproperlyConfigured(
                "REDIS_TLS=true requires REDIS_PASSWORD (hydrated by entrypoint.sh "
                "from Secret Manager); refusing to fall back to a plaintext connection"
            )
        # channels_redis (>= 4) accepts dict-form host entries; the dict is
        # unpacked into `aioredis.ConnectionPool.from_url(address, **rest)`
        # (see channels_redis/utils.py::create_pool), so redis-py's SSL
        # kwargs flow through. SERVER_AUTHENTICATION on GCP Memorystore
        # needs the instance CA to verify the server cert — when present,
        # the CA PEM is passed via `ssl_ca_data` so we never have to write
        # the cert to disk or mutate the system trust store. When absent
        # (tests, or environments that haven't shipped the CA bundle yet),
        # redis-py falls back to the system trust store with cert_reqs
        # still required.
        ca_pem = env.get("REDIS_CA_PEM", "")
        if not ca_pem.strip():
            # ADR-008-R6 fail-closed: the GCP runtime delivers the
            # Memorystore server CA alongside the AUTH token in Secret
            # Manager, and entrypoint.sh exports both as a unit. If the
            # CA didn't make it into the env, either Terraform hasn't
            # been re-applied with the new payload yet or the entrypoint
            # block was bypassed — both are misconfigurations, not
            # "fall back to system trust" cases. Memorystore uses a
            # private CA, so the system trust store could not validate
            # the cert anyway; this guard surfaces the misconfiguration
            # at startup rather than as an opaque TLS handshake failure
            # later.
            raise ImproperlyConfigured(
                "REDIS_TLS=true requires REDIS_CA_PEM (hydrated by entrypoint.sh "
                "from the Memorystore server_ca_cert in Secret Manager); refusing "
                "to fall back to the system trust store, which cannot validate the "
                "Memorystore private CA"
            )
        address = f"rediss://:{password}@{host}:{port}/0"
        # Use the raw CA value (do not strip) — the PEM block's
        # trailing newline matters for some TLS implementations and the
        # canonical form ends with one.
        host_entry = {
            "address": address,
            "ssl_cert_reqs": "required",
            "ssl_ca_data": ca_pem,
        }
        hosts: list[object] = [host_entry]
    else:
        hosts = [(host, port)]

    return {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": hosts},
        },
    }
