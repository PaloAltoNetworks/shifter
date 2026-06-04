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
                             on a private network — the AWS and pre-#963 GCP
                             shape).
    2. REDIS_HOST + REDIS_TLS -> rediss://<password>@host:port/0 URL host.
                                 REDIS_PASSWORD is hydrated by entrypoint.sh
                                 from Secret Manager (ADR-008-R6).

Fail closed when the TLS flag is on but no password / CA was hydrated —
silent fallback to plaintext is the failure mode #963 was opened to close.
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
    """
    from django.core.exceptions import ImproperlyConfigured

    host = env.get("REDIS_HOST", "").strip()
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
        "channel-layer posture: backend=%s explicit_backend=%s redis_host_present=%s redis_port=%s redis_tls=%s",
        safe_log_value(posture["backend"]),
        safe_log_value(posture["explicit_backend"]),
        posture["redis_host_present"],
        posture["redis_port"],
        posture["redis_tls"],
    )
