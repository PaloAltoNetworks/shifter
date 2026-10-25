"""Engine app configuration."""

from django.apps import AppConfig


class EngineConfig(AppConfig):
    """Configuration for the engine app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "engine"
    verbose_name = "Shifter Engine"

    def ready(self) -> None:
        """Register canonical range authority mutation fences."""
        import engine.signals  # noqa: F401
        from engine.services._authorization_inventory import register_authorization_range_inventory

        register_authorization_range_inventory()
