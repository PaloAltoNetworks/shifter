"""Management app configuration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.apps import AppConfig
from django.conf import settings
from django.db.models.signals import post_save

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


class ManagementConfig(AppConfig):
    """Django app configuration for the management (platform admin) app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "management"

    def ready(self) -> None:
        """Register user-profile signal handlers on app startup."""
        from . import services

        def on_user_created(
            sender: type[User],
            instance: User,
            created: bool,
            **kwargs: object,
        ) -> None:
            """Create a UserProfile when a new user is first saved."""
            if created:
                services.create_user_profile(instance)

        def on_user_saved(
            sender: type[User],
            instance: User,
            **kwargs: object,
        ) -> None:
            """Ensure an existing user without a profile gets one on save."""
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
            logger.exception("Failed to register user profile signal handlers")
            raise
