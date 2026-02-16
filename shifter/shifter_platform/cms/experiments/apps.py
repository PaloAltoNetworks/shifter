"""Experiments app configuration."""

from django.apps import AppConfig


class ExperimentsConfig(AppConfig):
    """Configuration for the experiments app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "cms.experiments"
    label = "experiments"
    verbose_name = "Experiments"
