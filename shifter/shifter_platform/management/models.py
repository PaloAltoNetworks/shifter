"""Management models.

Platform administration models for user profiles and activity logging.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.db import models

if TYPE_CHECKING:
    pass


class UserProfile(models.Model):
    """Extended user data for soft delete, anonymization, and user type.

    Attributes:
        user: The associated Django user.
        cognito_sub: Cognito user pool subject identifier.
        user_type: Type of user (standard, ctf_organizer, ctf_participant).
        active_ctf_event: Active CTF event for participant users.
        deleted_at: Soft delete timestamp.
        anonymized_at: When user data was anonymized.
    """

    USER_TYPE_CHOICES = [
        ("standard", "Standard User"),
        ("ctf_organizer", "CTF Organizer"),
        ("ctf_participant", "CTF Participant"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    cognito_sub = models.CharField(
        max_length=36,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        help_text="Cognito user pool subject identifier (UUID)",
    )
    user_type = models.CharField(
        max_length=20,
        choices=USER_TYPE_CHOICES,
        default="standard",
        db_index=True,
        help_text="Type of user account",
    )
    active_ctf_event = models.ForeignKey(
        "ctf.CTFEvent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="active_participants_profiles",
        help_text="Active CTF event for participant users",
    )
    deleted_at = models.DateTimeField(null=True, blank=True)
    anonymized_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "mission_control_userprofile"
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"

    def __str__(self) -> str:
        return f"Profile for {self.user.email}"

    @property
    def is_deleted(self) -> bool:
        """Return True if user has been soft-deleted."""
        return self.deleted_at is not None

    @property
    def is_ctf_organizer(self) -> bool:
        """Return True if user is a CTF organizer."""
        return self.user_type == "ctf_organizer"

    @property
    def is_ctf_participant(self) -> bool:
        """Return True if user is a CTF participant."""
        return self.user_type == "ctf_participant"

    @property
    def is_standard_user(self) -> bool:
        """Return True if user is a standard user."""
        return self.user_type == "standard"


class ActivityLog(models.Model):
    """Generic activity/event log for analytics and auditing."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activities",
    )
    action = models.CharField(max_length=100, db_index=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "mission_control_activitylog"
        ordering = ["-timestamp"]
        verbose_name = "Activity Log"
        verbose_name_plural = "Activity Logs"

    def __str__(self):
        user_str = self.user.email if self.user else "anonymous"
        return f"{self.action} by {user_str} at {self.timestamp}"

    @classmethod
    def log(cls, action: str, user=None, **metadata):
        """Convenience method to log an activity."""
        return cls.objects.create(user=user, action=action, metadata=metadata)
