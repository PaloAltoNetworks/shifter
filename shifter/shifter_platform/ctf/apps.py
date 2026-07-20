"""CTF app configuration."""

from django.apps import AppConfig


class CtfConfig(AppConfig):
    """Configuration for CTF app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "ctf"
    verbose_name = "CTF Management"

    def ready(self) -> None:
        """Perform app initialization when Django starts."""
        import ctf.signals  # noqa: F401 — register signal receivers
        from ctf.services.notification.realtime import register_ctf_notifications

        register_ctf_notifications()
        from ctf.services.range.visibility import register_ctf_visibility_policy

        register_ctf_visibility_policy()
