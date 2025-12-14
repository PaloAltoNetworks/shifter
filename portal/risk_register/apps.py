"""Risk Register app configuration."""

from django.apps import AppConfig


class RiskRegisterConfig(AppConfig):
    """Configuration for the Risk Register Django app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "risk_register"
    verbose_name = "Risk Register"
