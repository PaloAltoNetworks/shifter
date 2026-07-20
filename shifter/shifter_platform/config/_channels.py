"""Django Channels (Redis) layer configuration.

Extracted from ``config/settings.py`` to keep that module under the
500-line cap (Sonar S104). Pure functions live here; the module is
imported by ``config.settings`` to populate the ``CHANNEL_LAYERS``
setting.

Backend selection (ADR-018, #849) is an explicit, environment-owned
posture, decoupled from the portal ``enable_autoscaling`` topology:

    CHANNEL_LAYER_BACKEND=redis     -> Redis channel layer; REDIS_HOST is
                                       REQUIRED. Missing host fails closed
                                       (ImproperlyConfigured) rather than
                                       silently degrading to in-memory.
    CHANNEL_LAYER_BACKEND=in_memory -> InMemoryChannelLayer, even if a stray
                                       REDIS_HOST is present. The drift stays
                                       observable via the startup posture log.
    CHANNEL_LAYER_BACKEND unset     -> legacy REDIS_HOST-presence heuristic
                                       (local dev, pytest): host present ->
                                       Redis, absent -> InMemoryChannelLayer.

Once the backend resolves to Redis, the connection posture is derived from
the env, in order of preference:
    1. REDIS_HOST, no TLS -> channels_redis tuple host form (plaintext Redis
                             on a private network — the pre-hardening shape).
    2. REDIS_HOST + REDIS_TLS -> rediss://<password>@host:port/0 URL host.
                                 REDIS_PASSWORD is hydrated by entrypoint.sh
                                 from Secret Manager (ADR-008-R6).

When TLS is on, REDIS_CA_MODE selects how the server certificate is trusted:
    - pem (default when unset): verify against the CA bundle in REDIS_CA_PEM.
      GCP Memorystore uses a private CA, so a missing CA fails closed (#963).
    - system: verify against the OS trust store. AWS ElastiCache (#938)
      presents a server cert chained to a public Amazon CA already in the
      system trust store, so no REDIS_CA_PEM is needed; certificate
      verification still stays required.

Fail closed when the TLS flag is on but no password was hydrated, the chosen
trust mode is unknown, or REDIS_CA_MODE=pem with no CA — silent fallback to
plaintext (or to unverified TLS) is the failure mode #963 was opened to close.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from shared.log_sanitize import safe_log_value

__all__ = ["_build_channel_layers"]

_logger = logging.getLogger(__name__)

_IN_MEMORY = "in_memory"
_REDIS = "redis"
_VALID_BACKENDS = (_IN_MEMORY, _REDIS)


def _resolve_backend(env: Mapping[str, str]) -> str:
    """Resolve the channel-layer backend (``in_memory`` or ``redis``).

    The explicit ``CHANNEL_LAYER_BACKEND`` posture wins; it is independent of
    the portal ``enable_autoscaling`` topology (ADR-018). A ``redis`` posture
    requires ``REDIS_HOST`` and fails closed when it is absent. When the knob
    is unset (local dev / pytest), the legacy ``REDIS_HOST``-presence
    heuristic decides so those environments need no opt-in.
    """
    from django.core.exceptions import ImproperlyConfigured

    backend = env.get("CHANNEL_LAYER_BACKEND", "").strip().lower()
    host = env.get("REDIS_HOST", "").strip()

    if backend == _REDIS:
        if not host:
            raise ImproperlyConfigured(
                "CHANNEL_LAYER_BACKEND=redis requires REDIS_HOST; refusing to "
                "fall back to InMemoryChannelLayer (the silent-degradation "
                "failure mode #849 was opened to close)"
            )
        return _REDIS
    if backend == _IN_MEMORY:
        return _IN_MEMORY
    if backend:
        raise ImproperlyConfigured(f"CHANNEL_LAYER_BACKEND must be one of {_VALID_BACKENDS}, got {backend!r}")

    # Unset: preserve the pre-#849 host-presence heuristic.
    return _REDIS if host else _IN_MEMORY


def _build_redis_layer(env: Mapping[str, str]) -> dict[str, dict[str, object]]:
    """Build the ``channels_redis`` layer config from the env.

    The caller guarantees ``REDIS_HOST`` is present (via ``_resolve_backend``).
    The AUTH/TLS/CA fail-closed posture is resolved by the shared
    ``config._redis.resolve_redis_connection`` so this layer and the
    launch-admission cache (#322) never drift into two different, independently
    validated Redis security postures. The dict-form host entry is unpacked into
    ``aioredis.ConnectionPool.from_url(address, **rest)`` (see
    channels_redis/utils.py::create_pool), so redis-py's SSL kwargs flow
    through; the channels layer uses logical DB 0.
    """
    from config._redis import redis_tls_ssl_kwargs, redis_tls_url, resolve_redis_connection

    conn = resolve_redis_connection(env)
    if conn.tls:
        host_entry: dict[str, object] = {"address": redis_tls_url(conn, 0), **redis_tls_ssl_kwargs(conn)}
        hosts: list[object] = [host_entry]
    else:
        hosts = [(conn.host, conn.port)]

    return {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": hosts},
        },
    }


def _build_channel_layers(env: Mapping[str, str]) -> dict[str, dict[str, object]]:
    """Build CHANNEL_LAYERS from the given mapping (typically os.environ).

    Pure function so it is unit-testable without touching real settings.
    """
    if _resolve_backend(env) == _IN_MEMORY:
        return {
            "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
        }
    return _build_redis_layer(env)


def describe_channel_layer_posture(env: Mapping[str, str]) -> dict[str, object]:
    """Return the non-secret channel-layer posture for startup observability.

    Reports the resolved backend plus the inputs that decided it, so a
    provisioned-but-unused Redis (an ``in_memory`` backend with a present
    ``REDIS_HOST``) is visible rather than silent. Carries no secret or
    topology-disclosing values — host/password/CA are never included, only
    booleans and the (non-secret) port.
    """
    raw_backend = env.get("CHANNEL_LAYER_BACKEND", "").strip()
    host = env.get("REDIS_HOST", "").strip()
    return {
        "backend": _resolve_backend(env),
        "explicit_backend": raw_backend or None,
        "redis_host_present": bool(host),
        "redis_port": int(env.get("REDIS_PORT", "6379")) if host else None,
        "redis_tls": env.get("REDIS_TLS", "").strip().lower() == "true",
        "redis_ca_mode": env.get("REDIS_CA_MODE", "").strip().lower() or None,
    }


def log_channel_layer_posture(env: Mapping[str, str], *, logger: logging.Logger | None = None) -> None:
    """Emit a single non-secret startup record of the active channel-layer
    backend (#849 AC2). Derives from the same decision path that builds
    ``CHANNEL_LAYERS`` so the log reflects the backend actually selected, not
    a Terraform assumption. Call once per process (see ``config/asgi.py``).
    """
    log = logger or _logger
    posture = describe_channel_layer_posture(env)
    log.info(
        "channel-layer posture: backend=%s explicit_backend=%s redis_host_present=%s "
        "redis_port=%s redis_tls=%s redis_ca_mode=%s",
        safe_log_value(posture["backend"]),
        safe_log_value(posture["explicit_backend"]),
        posture["redis_host_present"],
        posture["redis_port"],
        posture["redis_tls"],
        safe_log_value(posture["redis_ca_mode"]),
    )
