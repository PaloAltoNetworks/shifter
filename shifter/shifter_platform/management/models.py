"""Management models.

Platform administration models for user profiles and activity logging.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

if TYPE_CHECKING:
    from django.contrib.auth.models import User


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
    suspended_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Temporary-suspension discriminator (issue #1943). When set, the "
            "account is suspended: authentication is blocked (User.is_active is "
            "held False) while assignments and owned resources are retained. It "
            "distinguishes a reversible security hold from a plain deactivation "
            "and from soft deletion; User.is_active remains the sole "
            "authentication-enforcement bit."
        ),
    )
    deleted_at = models.DateTimeField(null=True, blank=True)
    anonymized_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        """Table mapping, labels, and CTF-account identity invariants."""

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
    def is_deleted(self) -> bool:
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
        """Table mapping, default ordering, and labels for the activity log."""

        db_table = "mission_control_activitylog"
        ordering = ["-timestamp"]
        verbose_name = "Activity Log"
        verbose_name_plural = "Activity Logs"

    def __str__(self) -> str:
        user_str = self.user.email if self.user else "anonymous"
        return f"{self.action} by {user_str} at {self.timestamp}"

    @classmethod
    def log(cls, action: str, user: User | None = None, **metadata: Any) -> ActivityLog:
        """Convenience method to log an activity."""
        return cls.objects.create(user=user, action=action, metadata=metadata)


class ModelAccessGroupEligibility(models.Model):
    """Explicit funded-access policy for one canonical Django auth group.

    Direct group membership remains only an applicability fact.  A funded
    model-access binding additionally requires either administrator-managed
    membership or an independent spending approval recorded here.
    """

    group = models.OneToOneField(
        "auth.Group",
        on_delete=models.CASCADE,
        related_name="model_access_eligibility",
    )
    managed_membership = models.BooleanField(default=False)
    spending_approved = models.BooleanField(default=False)
    revision = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Database table and integrity constraints for the eligibility record."""

        db_table = "management_model_access_group_eligibility"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(revision__gt=0),
                name="management_model_access_group_revision_positive",
            )
        ]

    def __str__(self) -> str:
        return f"Model-access eligibility for {self.group.name} (revision {self.revision})"


class Principal(models.Model):
    """Stable human or service identity, separate from credentials and contacts."""

    class Kind(models.TextChoices):
        """Closed durable principal kinds."""

        HUMAN = "human", "Human"
        SERVICE = "service", "Service"

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="identity_principal",
    )
    name = models.CharField(max_length=200, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_service_principals",
    )
    responsible_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="responsible_service_principals",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Database metadata and identity-shape constraints."""

        db_table = "management_principal"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(kind__in=("human", "service")),
                name="principal_kind_closed",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(kind="human", user__isnull=False, created_by__isnull=True, responsible_user__isnull=True)
                    | models.Q(kind="service", user__isnull=True)
                ),
                name="principal_human_service_shape",
            ),
        ]

    def __str__(self) -> str:
        return f"principal:{self.uuid}"


class PrincipalConflictError(ValueError):
    """Principal or provider binding conflicts with durable identity."""


class ProviderBinding(models.Model):
    """Immutable exact provider tuple attached to one principal."""

    principal = models.ForeignKey(Principal, on_delete=models.PROTECT, related_name="provider_bindings")
    issuer = models.CharField(max_length=255)
    subject = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Database metadata and immutable tuple constraints."""

        db_table = "management_provider_binding"
        constraints = [
            models.UniqueConstraint(fields=["issuer", "subject"], name="uniq_provider_principal_tuple"),
            models.CheckConstraint(
                condition=~models.Q(issuer="") & ~models.Q(subject=""),
                name="provider_binding_nonblank_tuple",
            ),
        ]

    def __str__(self) -> str:
        return f"provider-binding:{self.pk}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk:
            prior = type(self).objects.filter(pk=self.pk).values("principal_id", "issuer", "subject").first()
            if prior is None or (
                prior["principal_id"] != self.principal_id
                or prior["issuer"] != self.issuer
                or prior["subject"] != self.subject
            ):
                raise PrincipalConflictError("Provider binding is immutable")
        super().save(*args, **kwargs)


class ServiceCredentialAdmission(models.Model):
    """Administrator-configured limits for one native service identity."""

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    binding = models.ForeignKey(ProviderBinding, on_delete=models.PROTECT, related_name="service_admissions")
    audience = models.URLField(max_length=500)
    scopes = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Service credentials store admission metadata, never provider secrets."""

        db_table = "management_service_credential_admission"
        constraints = [
            models.UniqueConstraint(
                fields=["binding", "audience"],
                condition=models.Q(is_active=True),
                name="unique_active_service_admission",
            )
        ]

    def __str__(self) -> str:
        return f"service-credential:{self.uuid}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk:
            fields = ("binding_id", "audience", "scopes", "uuid")
            previous = type(self).objects.filter(pk=self.pk).values(*fields).first()
            if previous is None or any(previous[field] != getattr(self, field) for field in fields):
                raise PrincipalConflictError("Service admission is immutable; disable and register a new binding")
        super().save(*args, **kwargs)
