"""Management models.

Platform administration models for user profiles and activity logging.
"""

from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    """Extended user data for soft delete and anonymization."""

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
    deleted_at = models.DateTimeField(null=True, blank=True)
    anonymized_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "mission_control_userprofile"
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"

    def __str__(self):
        return f"Profile for {self.user.email}"

    @property
    def is_deleted(self):
        return self.deleted_at is not None


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
