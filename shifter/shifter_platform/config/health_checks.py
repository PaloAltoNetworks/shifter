"""Additional portal health-check plugins.

The public ``/health`` endpoint is the ALB readiness surface. Keep new probes
inside the existing django-health-check registry so the endpoint preserves one
coarse response contract while reflecting the configured runtime dependencies.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from health_check.backends import HealthCheck as HealthCheckPluginBase
from health_check.exceptions import ServiceUnavailable
from health_check.plugins import plugin_dir

from shared.log_sanitize import safe_log_value

__all__ = [
    "ChannelLayerRedisHealthCheck",
    "channel_layer_uses_redis",
    "register_channel_layer_redis_health_check",
]

_logger = logging.getLogger(__name__)
_REDIS_CHANNEL_LAYER = "channels_redis.core.RedisChannelLayer"
_PROBE_TIMEOUT_SECONDS = 2.0


def channel_layer_uses_redis() -> bool:
    """Return whether the resolved default Channels backend is Redis."""
    channel_layers = getattr(settings, "CHANNEL_LAYERS", {})
    default_layer = channel_layers.get("default", {})
    return default_layer.get("BACKEND") == _REDIS_CHANNEL_LAYER


class ChannelLayerRedisHealthCheck(HealthCheckPluginBase):
    """Probe the configured Redis-backed Channels layer."""

    def check_status(self) -> None:
        try:
            self._probe()
        except Exception as exc:
            _logger.warning("channel-layer Redis readiness failed: %s", safe_log_value(exc.__class__.__name__))
            self.add_error(ServiceUnavailable("Channel layer Redis unavailable"))

    def _probe(self) -> None:
        async_to_sync(_probe_configured_channel_layer)()


def register_channel_layer_redis_health_check() -> None:
    """Register Redis readiness only when the default channel layer is Redis."""
    if not channel_layer_uses_redis():
        return
    if any(plugin is ChannelLayerRedisHealthCheck for plugin, _options in plugin_dir._registry):
        return
    plugin_dir.register(ChannelLayerRedisHealthCheck)


async def _probe_configured_channel_layer() -> None:
    layer = get_channel_layer()
    if layer is None:
        raise ServiceUnavailable("Default channel layer is unavailable")
    await asyncio.wait_for(_round_trip(layer), timeout=_PROBE_TIMEOUT_SECONDS)


async def _round_trip(layer: Any) -> None:
    channel = await layer.new_channel("health.check")
    message = {"type": "health.check", "id": uuid.uuid4().hex}
    await layer.send(channel, message)
    received = await layer.receive(channel)
    if received != message:
        raise ServiceUnavailable("Default channel layer returned an unexpected health-check response")
