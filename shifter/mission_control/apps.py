"""Mission Control app configuration."""

from django.apps import AppConfig


class MissionControlConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "mission_control"

    def ready(self):
        import mission_control.signals  # noqa: F401
