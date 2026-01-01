"""Documentation app configuration."""

from django.apps import AppConfig


class DocumentationConfig(AppConfig):
    """Configuration for the Documentation Django app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "documentation"
    verbose_name = "Documentation"
