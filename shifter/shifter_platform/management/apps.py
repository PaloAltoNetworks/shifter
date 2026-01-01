"""Management app configuration."""

import logging

from django.apps import AppConfig
from django.conf import settings
from django.db.models.signals import post_save

logger = logging.getLogger(__name__)


class ManagementConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "management"

    def ready(self):
        from . import services

        def on_user_created(sender, instance, created, **kwargs):
            if created:
                services.create_user_profile(instance)

        def on_user_saved(sender, instance, **kwargs):
            if not hasattr(instance, "profile"):
                services.save_user_profile(instance)

        try:
            post_save.connect(
                on_user_created,
                sender=settings.AUTH_USER_MODEL,
                dispatch_uid="management_create_user_profile",
            )
            post_save.connect(
                on_user_saved,
                sender=settings.AUTH_USER_MODEL,
                dispatch_uid="management_save_user_profile",
            )
            logger.debug("Registered user profile signal handlers")
        except Exception:
            logger.error("Failed to register user profile signal handlers")
            raise
