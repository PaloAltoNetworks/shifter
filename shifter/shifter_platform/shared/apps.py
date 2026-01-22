"""Django app configuration for shared module.

This is a minimal Django app that provides shared contracts and schemas.
The actual implementation is in shifter/shared/ - this app just provides
Django app registration for INSTALLED_APPS.
"""

from django.apps import AppConfig


class SharedConfig(AppConfig):
    """Django app configuration for shared module."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "shared"
    verbose_name = "Shared Contracts"
