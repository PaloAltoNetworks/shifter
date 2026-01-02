"""Django app configuration for shared."""

from django.apps import AppConfig


class SharedConfig(AppConfig):
    """Configuration for the shared contracts app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "shared"
