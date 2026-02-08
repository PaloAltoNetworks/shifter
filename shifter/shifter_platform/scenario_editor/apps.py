"""Scenario Editor app configuration."""

from django.apps import AppConfig


class ScenarioEditorConfig(AppConfig):
    """Configuration for the Scenario Editor app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "scenario_editor"
    verbose_name = "Scenario Editor"
