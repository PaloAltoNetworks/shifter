"""Django app hooks for cross-cutting portal configuration."""

from __future__ import annotations

from django.apps import AppConfig


class PortalConfig(AppConfig):
    """Register config-level startup hooks for the portal runtime."""

    name = "config"

    def ready(self) -> None:
        from config.health_checks import register_channel_layer_redis_health_check

        register_channel_layer_redis_health_check()
