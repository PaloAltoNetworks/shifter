"""Management models.

Platform administration models for user profiles and activity logging.
"""

from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class UserProfile(models.Model):
    """Extended user data for soft delete and anonymization."""

    USER_TYPE_CHOICES = [
        ("standard", "Standard"),
        ("ctf_organizer", "CTF Organizer"),
        ("ctf_participant", "CTF Participant"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    cognito_sub = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        help_text=(
            "Provider subject identifier (opaque, case-sensitive; issue #1521). "
            "Historically a Cognito user pool UUID; also used for the GCP "
            "Identity Platform Firebase UID and other provider subjects. "
            "Paired with `issuer` for the bound (issuer, subject) identity key."
        ),
    )
    issuer = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=(
            "Provider issuer (opaque, case-sensitive; issue #1521) paired with "
            "cognito_sub as the bound (issuer, subject) identity key. Empty for a "
            "legacy row bound before this field existed; acquired once, on the "
            "next login presenting the same subject "
            "(see management.services.bind_provider_identity)."
        ),
    )
    user_type = models.CharField(
        max_length=20,
        choices=USER_TYPE_CHOICES,
        default="standard",
        help_text="User role type for routing and access control",
    )
    is_ctf_account = models.BooleanField(
        default=False,
        help_text="Immutable origin marker for temporary local CTF participant accounts",
    )
    must_change_password = models.BooleanField(
        default=False,
        help_text="Require a temporary CTF account to change its bootstrap password",
    )
    # Soft reference to ctf.CTFEvent (no cross-layer FK).
    # DB column stays "active_ctf_event_id" for backward compatibility.
    # UUIDField because CTFEvent.pk is a UUID.
    active_ctf_event_id = models.UUIDField(
        null=True,
        blank=True,
        db_column="active_ctf_event_id",
        help_text="Active CTF event ID for participant users",
    )
    cognito_groups = models.JSONField(
        default=list,
        blank=True,
        help_text="Cognito group names captured from verified OIDC claims at login",
    )
    ORGANIZER_GRANT_SOURCE_CHOICES = [
        ("", "None"),
        ("provider", "Provider group"),
        ("local", "Local assignment"),
    ]
    organizer_grant_source = models.CharField(
        max_length=16,
        choices=ORGANIZER_GRANT_SOURCE_CHOICES,
        blank=True,
        default="",
        help_text=(
            "Provenance of CTF Organizer membership (issue #1516): 'provider' is "
            "auto-revoked when admin-controlled provider evidence disappears at "
            "login; 'local' is an explicit local assignment and is never "
            "auto-revoked. Empty when the user is not a tracked organizer."
        ),
    )
    deleted_at = models.DateTimeField(null=True, blank=True)
    anonymized_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "mission_control_userprofile"
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(is_ctf_account=False)
                    | models.Q(user_type="ctf_participant", cognito_sub__isnull=True, issuer="")
                ),
                name="ctf_account_profile_identity_invariants",
            )
        ]

    def __str__(self) -> str:
        return f"Profile for {self.user.email}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Prevent the temporary-account origin marker from being cleared."""
        if self.pk and not self.is_ctf_account and type(self).objects.filter(pk=self.pk, is_ctf_account=True).exists():
            raise ValidationError({"is_ctf_account": "The temporary CTF account marker is immutable."})
        super().save(*args, **kwargs)

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    @property
    def is_ctf_organizer(self) -> bool:
        """Deprecated: use shared.auth.is_ctf_organizer(user) instead."""
        return self.user.groups.filter(name="CTF Organizer").exists()

    @property
    def is_ctf_participant(self) -> bool:
        """Deprecated: use shared.auth.is_ctf_participant(user) instead."""
        return self.user.groups.filter(name="CTF Participant").exists()

    @property
    def is_standard_user(self) -> bool:
        return not self.is_ctf_organizer and not self.is_ctf_participant


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
