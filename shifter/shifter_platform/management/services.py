"""Management service interface.

Platform administration for Shifter platform.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from django.utils import timezone

from risk_register.models import AuditLog
from risk_register.services import audit_log
from shared.constants import USER_CANNOT_BE_NONE

from .models import ActivityLog, UserProfile

if TYPE_CHECKING:
    from uuid import UUID

    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


def log_activity(action: str, user: User | None, **metadata: Any) -> None:
    """Log an activity for audit trail.

    DEPRECATED: Use risk_register.services.audit_log() instead.
    This function is retained for backward compatibility only.

    Args:
        action: Action identifier (e.g., "range_launched", "agent_uploaded")
        user: User who performed the action, or None for system actions
        **metadata: Additional context to store with the log entry

    Raises:
        TypeError: If action is not a string
        ValueError: If action is empty or user is unsaved
    """
    if not isinstance(action, str):
        raise TypeError("action must be a string")
    if not action.strip():
        raise ValueError("action cannot be empty")
    if user is not None and user.pk is None:
        raise ValueError("user must have a primary key")

    user_display = user.email if user else "anonymous"

    try:
        ActivityLog.log(action, user=user, **metadata)
        logger.debug("Logged activity '%s' for user %s", action, user_display)
    except Exception:
        logger.error("Failed to log activity '%s' for user %s", action, user_display)
        raise


def get_user_profile(user: User) -> UserProfile:
    """Get or create the profile for a user.

    Args:
        user: The user to get profile for

    Returns:
        UserProfile instance for the user

    Raises:
        TypeError: If user is None
        ValueError: If user has no primary key (unsaved)
    """
    if user is None:
        raise TypeError(USER_CANNOT_BE_NONE)
    if user.pk is None:
        raise ValueError("user must have a primary key")

    try:
        profile, created = UserProfile.objects.get_or_create(user=user)
        if created:
            logger.debug("Created new profile for user %s", user.email)
        else:
            logger.debug("Retrieved profile for user %s", user.email)
        return profile
    except Exception:
        logger.error("Failed to get/create profile for user %s", user.email)
        raise


def mark_user_deleted(user: User, admin_user: User | None = None) -> None:
    """Soft delete a user by setting deleted_at timestamp.

    Creates profile if it doesn't exist.

    Args:
        user: The user to mark as deleted
        admin_user: The admin user performing the deletion (for audit)

    Raises:
        TypeError: If user is None
        ValueError: If user has no primary key (unsaved)
    """
    profile = get_user_profile(user)

    if profile.is_deleted:
        logger.warning("User %s is already deleted, updating timestamp", user.email)

    try:
        profile.deleted_at = timezone.now()
        profile.save(update_fields=["deleted_at"])

        # Audit log user deletion
        audit_log(
            entity_type=AuditLog.EntityType.USER,
            entity_id=user.id,
            action=AuditLog.Action.DELETE,
            actor_type=AuditLog.ActorType.USER if admin_user else AuditLog.ActorType.SYSTEM,
            actor_id=admin_user.id if admin_user else None,
            previous_state={"email": user.email},
        )

        logger.debug("Marked user %s as deleted", user.email)
    except Exception:
        logger.error("Failed to mark user %s as deleted", user.email)
        raise


def create_user_profile(user: User) -> None:
    """Create a UserProfile for a user.

    Args:
        user: The user to create profile for

    Raises:
        TypeError: If user is None
        ValueError: If user has no primary key (unsaved)
    """
    if user is None:
        raise TypeError(USER_CANNOT_BE_NONE)
    if user.pk is None:
        raise ValueError("user must have a primary key")

    try:
        UserProfile.objects.create(user=user)
        logger.debug("Created profile for user %s", user.email)
    except Exception:
        logger.error("Failed to create profile for user %s", user.email)
        raise


def save_user_profile(user: User) -> None:
    """Ensure a UserProfile exists for a user.

    Args:
        user: The user to ensure profile for

    Raises:
        TypeError: If user is None
        ValueError: If user has no primary key (unsaved)
    """
    if user is None:
        raise TypeError(USER_CANNOT_BE_NONE)
    if user.pk is None:
        raise ValueError("user must have a primary key")

    try:
        UserProfile.objects.get_or_create(user=user)
        logger.debug("Ensured profile for user %s", user.email)
    except Exception:
        logger.error("Failed to ensure profile for user %s", user.email)
        raise


def update_cognito_sub(user: User, cognito_sub: str) -> None:
    """Update the Cognito sub for a user's profile.

    Args:
        user: The user to update
        cognito_sub: The Cognito sub identifier

    Raises:
        TypeError: If user is None or cognito_sub is None
        ValueError: If user has no primary key or cognito_sub is empty
    """
    if user is None:
        raise TypeError(USER_CANNOT_BE_NONE)
    if user.pk is None:
        raise ValueError("user must have a primary key")
    if cognito_sub is None:
        raise TypeError("cognito_sub cannot be None")
    if not cognito_sub.strip():
        raise ValueError("cognito_sub cannot be empty")

    try:
        profile = get_user_profile(user)
        if profile.cognito_sub == cognito_sub:
            logger.debug("cognito_sub unchanged for user %s", user.email)
            return

        profile.cognito_sub = cognito_sub
        profile.save(update_fields=["cognito_sub"])
        logger.info("Updated cognito_sub for user %s: %s", user.email, cognito_sub)
    except Exception:
        logger.error("Failed to update cognito_sub for user %s", user.email)
        raise


def set_active_ctf_event(user: User, event_id: UUID | None) -> None:
    """Set or clear the active CTF event for a user.

    Args:
        user: The user to update.
        event_id: CTF event UUID PK to set, or None to clear.
    """
    profile = get_user_profile(user)
    profile.active_ctf_event_id = event_id
    profile.save(update_fields=["active_ctf_event_id"])
