"""Management app configuration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.apps import AppConfig
from django.conf import settings
from django.db import transaction
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
        from shared.principal_port import bind_principal_directory

        from . import services

        bind_principal_directory(
            services.principal_for_user,
            services.resolve_principal,
            services.resolve_principal_uuid,
            services.resolve_verified_principal,
            services.principal_identity_for_user,
        )

        def on_user_saved(
            sender: type[User],
            instance: User,
            raw: bool = False,
            **kwargs: object,
        ) -> None:
            """Reconcile identity rows on every save, including a failed-create retry.

            A caller may insert User in autocommit before this signal runs.
            Keep its derived rows atomic and repair them on any subsequent save;
            authentication still refuses an absent principal during an outage.
            """
            if raw:
                return
            with transaction.atomic():
                services.save_user_profile(instance)
                services.ensure_human_principal(instance)

        try:
            post_save.connect(
                on_user_saved,
                sender=settings.AUTH_USER_MODEL,
                dispatch_uid="management_save_user_profile",
                weak=False,
            )
            logger.debug("Registered user profile signal handlers")
        except Exception:
            logger.exception("Failed to register user profile signal handlers")
            raise
