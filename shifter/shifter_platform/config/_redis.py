"""Shared Redis connection posture (single source of truth).

Every Redis consumer in the portal — the Django Channels layer
(``config._channels``) and the ``launch_rate_limit`` admission cache (#322) —
derives its client configuration from :func:`resolve_redis_connection`, so the
fail-closed AUTH/TLS/CA security posture (ADR-008-R6, #963 for GCP Memorystore's
private CA, #938 for AWS ElastiCache's system trust) is defined exactly once.
Building a second, independently-validated Redis client config is the
drift/weakening failure mode this module exists to prevent.

The consumer-specific *shape* still lives with each consumer:
``config._channels`` formats a ``channels_redis`` layer (logical DB 0);
:func:`build_launch_rate_limit_cache` formats a Django ``RedisCache`` (logical
DB 1, distinct key prefix) so admission counters never collide with the channel
layer's pub/sub keys.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

__all__ = [
    "CA_MODE_PEM",
    "CA_MODE_SYSTEM",
    "RedisConnection",
    "build_launch_rate_limit_cache",
    "redis_configured",
    "redis_tls_ssl_kwargs",
    "redis_tls_url",
    "resolve_redis_connection",
]

CA_MODE_PEM = "pem"
CA_MODE_SYSTEM = "system"
_VALID_CA_MODES = (CA_MODE_PEM, CA_MODE_SYSTEM)

# Logical Redis DB for the launch-admission cache — distinct from the Channels
# layer (DB 0) so admission counters never share a keyspace with pub/sub state.
_LAUNCH_RATE_LIMIT_DB = 1
_LAUNCH_RATE_LIMIT_KEY_PREFIX = "mc-launch-rl"


@dataclass(frozen=True)
class RedisConnection:
    """Validated Redis connection posture.

    ``password`` and ``ca_pem`` are secrets: callers must keep them out of logs,
    metrics, process argv, and ConfigMaps — they belong only in the client
    connection config. ``ca_mode``/``ca_pem`` are meaningful only when ``tls``.
    """

    host: str
    port: int
    tls: bool
    password: str
    ca_mode: str
    ca_pem: str


def redis_configured(env: Mapping[str, str]) -> bool:
    """Return whether a Redis host is configured (non-blank ``REDIS_HOST``)."""
    return bool(env.get("REDIS_HOST", "").strip())


def resolve_redis_connection(env: Mapping[str, str]) -> RedisConnection:
    """Resolve and validate the Redis connection posture, failing closed.

    Enforces the AUTH/TLS/CA contract shared with the Channels layer: TLS
    requires a password; ``REDIS_CA_MODE`` defaults to ``pem`` and must be a
    known mode; ``pem`` mode requires a CA bundle. A silent downgrade to a
    plaintext or unverified-TLS connection is the failure mode #963 closed.
    """
    from django.core.exceptions import ImproperlyConfigured

    host = env.get("REDIS_HOST", "").strip()
    if not host:
        raise ImproperlyConfigured("resolve_redis_connection requires REDIS_HOST")
    port = int(env.get("REDIS_PORT", "6379"))
    tls = env.get("REDIS_TLS", "").strip().lower() == "true"
    password = env.get("REDIS_PASSWORD", "").strip()
    ca_mode = ""
    ca_pem = ""
    if tls:
        if not password:
            raise ImproperlyConfigured(
                "REDIS_TLS=true requires REDIS_PASSWORD (hydrated by entrypoint.sh "
                "from Secret Manager); refusing to fall back to a plaintext connection"
            )
        ca_mode = env.get("REDIS_CA_MODE", "").strip().lower() or CA_MODE_PEM
        if ca_mode not in _VALID_CA_MODES:
            raise ImproperlyConfigured(f"REDIS_CA_MODE must be one of {_VALID_CA_MODES}, got {ca_mode!r}")
        if ca_mode == CA_MODE_PEM:
            ca_pem = env.get("REDIS_CA_PEM", "")
            if not ca_pem.strip():
                raise ImproperlyConfigured(
                    "REDIS_TLS with REDIS_CA_MODE=pem requires REDIS_CA_PEM (hydrated by "
                    "entrypoint.sh from the Memorystore server_ca_cert in Secret Manager); "
                    "refusing to fall back to the system trust store, which cannot validate "
                    "the Memorystore private CA"
                )
    return RedisConnection(host=host, port=port, tls=tls, password=password, ca_mode=ca_mode, ca_pem=ca_pem)


def redis_tls_url(conn: RedisConnection, db: int) -> str:
    """Build the ``rediss://`` URL for a TLS connection on logical DB ``db``."""
    return f"rediss://:{conn.password}@{conn.host}:{conn.port}/{db}"


def redis_tls_ssl_kwargs(conn: RedisConnection) -> dict[str, object]:
    """Build the redis-py SSL kwargs for a TLS connection.

    ``ssl_cert_reqs=required`` in both trust modes, so the server certificate is
    always verified. ``pem`` mode pins the private CA via ``ssl_ca_data``;
    ``system`` mode trusts the OS store but requires hostname verification so a
    publicly-trusted certificate for a different name cannot MITM the session.
    """
    kwargs: dict[str, object] = {"ssl_cert_reqs": "required"}
    if conn.ca_mode == CA_MODE_PEM:
        kwargs["ssl_ca_data"] = conn.ca_pem
    else:
        kwargs["ssl_check_hostname"] = True
    return kwargs


def build_launch_rate_limit_cache(env: Mapping[str, str]) -> dict[str, object]:
    """Build the ``launch_rate_limit`` Django ``CACHES`` entry (#322).

    Redis-backed when ``REDIS_HOST`` is configured (production, multi-worker
    correctness) or a process-local LocMemCache for tests / single-process dev.
    Reuses the shared Redis posture (no second client config), on logical DB 1
    with a distinct key prefix from the Channels layer. Django's built-in
    ``RedisCache`` forwards ``OPTIONS`` to ``redis.ConnectionPool.from_url``, so
    the same SSL kwargs the Channels layer uses apply here.
    """
    if not redis_configured(env):
        return {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "launch-rate-limit",
        }
    conn = resolve_redis_connection(env)
    cfg: dict[str, object] = {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "KEY_PREFIX": _LAUNCH_RATE_LIMIT_KEY_PREFIX,
    }
    if conn.tls:
        cfg["LOCATION"] = redis_tls_url(conn, _LAUNCH_RATE_LIMIT_DB)
        cfg["OPTIONS"] = redis_tls_ssl_kwargs(conn)
    else:
        cfg["LOCATION"] = f"redis://{conn.host}:{conn.port}/{_LAUNCH_RATE_LIMIT_DB}"
    return cfg
