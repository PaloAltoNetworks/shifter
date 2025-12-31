"""Engine app configuration."""

from django.apps import AppConfig


class EngineConfig(AppConfig):
    """Configuration for the engine app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "engine"
    verbose_name = "Shifter Engine"
