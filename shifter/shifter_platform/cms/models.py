"""CMS models - Asset hierarchy and content management models."""

from __future__ import annotations

import logging
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from encrypted_model_fields.fields import EncryptedCharField

# CredentialBase is defined locally below (migrated from mission_control)

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Abstract Base Models
# -----------------------------------------------------------------------------


class Asset(models.Model):
    """Abstract base for user-owned assets with soft delete.

    Provides common fields and behavior for all asset types:
    - name: User-friendly identifier
    - created_at: Automatic creation timestamp
    - deleted_at: Soft delete timestamp (None = active)

    Subclasses must define a 'user' ForeignKey field.
    """

    name = models.CharField(max_length=100, help_text="User-friendly name")
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    def __str__(self):
        return self.name

    @property
    def is_deleted(self):
        """Return True if this asset has been soft-deleted."""
        return self.deleted_at is not None

    @classmethod
    def active_for_user(cls, user):
        """Return non-deleted assets for a user.

        Args:
            user: The user to filter by

        Returns:
            QuerySet of active (non-deleted) assets for the user
        """
        return cls.objects.filter(user=user, deleted_at__isnull=True)


class FileAsset(Asset):
    """Abstract base class for file-backed assets stored in S3.

    Extends Asset with fields for S3 storage:
    - s3_key: Full S3 object key
    - original_filename: Original uploaded filename
    - file_size_bytes: File size for quota tracking
    - sha256_hash: Content hash for integrity/deduplication
    """

    s3_key = models.CharField(max_length=500, help_text="S3 object key")
    original_filename = models.CharField(max_length=255)
    file_size_bytes = models.PositiveBigIntegerField()
    sha256_hash = models.CharField(max_length=64)

    class Meta:
        abstract = True

    @property
    def file_size_mb(self):
        """Return file size in megabytes, rounded to 1 decimal."""
        return round(self.file_size_bytes / (1024 * 1024), 1)


class CredentialBase(Asset):
    """Abstract base for credential assets with expiration tracking.

    Extends Asset with credential-specific fields:
    - expires_at: Optional expiration timestamp
    - last_verified_at: Last external validation timestamp
    - last_used_at: Last provisioning use timestamp
    """

    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this credential expires (user sets at creation)",
    )
    last_verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last time credential was validated against external system",
    )
    last_used_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last time credential was used for provisioning",
    )

    class Meta:
        abstract = True

    @property
    def is_expired(self):
        """Return True if this credential has expired."""
        if not self.expires_at:
            return False
        return timezone.now() > self.expires_at


# -----------------------------------------------------------------------------
# Reference Models
# -----------------------------------------------------------------------------


class OperatingSystem(models.Model):
    """Reference table for supported operating systems.

    Used for categorizing file assets by their target platform.
    """

    slug = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    extensions = models.JSONField(default=list, help_text="File extensions that map to this OS (e.g., ['.msi'])")

    class Meta:
        ordering = ["name"]
        verbose_name = "Operating System"
        verbose_name_plural = "Operating Systems"

    def __str__(self):
        return self.name

    @classmethod
    def get_for_extension(cls, extension: str):
        """Find the OS that matches a given file extension.

        Args:
            extension: File extension with or without leading dot (e.g., '.msi' or 'msi')

        Returns:
            OperatingSystem instance if found, None otherwise
        """
        ext = extension.lower()
        if not ext.startswith("."):
            ext = f".{ext}"
        for os in cls.objects.all():
            if ext in os.extensions:
                return os
        return None


# -----------------------------------------------------------------------------
# Credential Models
# -----------------------------------------------------------------------------


class Credential(CredentialBase):
    """Unified credential model with type discrimination.

    Consolidates SCMCredential and NGFWDeploymentProfile into a single table
    with type-based field validation.

    Fields inherited from Asset (via CredentialBase):
        - name: User-friendly name (max 100 chars)
        - created_at: Auto-set on creation
        - deleted_at: Soft delete timestamp
        - is_deleted: Property

    Fields inherited from Credential abstract base:
        - expires_at: Expiration timestamp
        - last_verified_at: Last external validation
        - last_used_at: Last provisioning use
        - is_expired: Property

    Type-specific fields:
        SCM:
            - scm_folder_name (required)
            - scm_pin_id (required)
            - scm_pin_value (required, encrypted)
            - sls_region (required)
        DEPLOYMENT_PROFILE:
            - authcode (required, encrypted)
    """

    class Type(models.TextChoices):
        SCM = "scm", "SCM Registration"
        DEPLOYMENT_PROFILE = "deployment_profile", "NGFW Deployment Profile"

    class SLSRegion(models.TextChoices):
        AMERICAS = "americas", "Americas"
        EUROPE = "europe", "Europe"
        JAPAN = "japan", "Japan"
        ASIAPACIFIC = "asiapacific", "Asia Pacific"

    # Core fields
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="cms_credentials",
    )
    credential_type = models.CharField(
        max_length=30,
        choices=Type.choices,
    )

    # SCM fields (required for SCM type)
    scm_folder_name = models.CharField(max_length=255, blank=True, default="")
    scm_pin_id = models.CharField(max_length=255, blank=True, default="")
    scm_pin_value = EncryptedCharField(max_length=255, blank=True, default="")
    sls_region = models.CharField(
        max_length=50,
        choices=SLSRegion.choices,
        blank=True,
        default="",
    )

    # Deployment profile fields (required for DEPLOYMENT_PROFILE type)
    authcode = EncryptedCharField(max_length=100, blank=True, default="")

    # Track original values for immutability checks
    _original_credential_type: str | None = None
    _original_user_id: int | None = None
    _original_authcode: str | None = None
    _original_deleted_at = None
    _is_new: bool = True

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Credential"
        verbose_name_plural = "Credentials"
        # Uniqueness constraints - only for non-deleted credentials
        constraints = [
            # User + name must be unique (for non-deleted)
            models.UniqueConstraint(
                fields=["user", "name"],
                condition=models.Q(deleted_at__isnull=True),
                name="unique_active_credential_name_per_user",
            ),
            # User + authcode must be unique for deployment profiles (for non-deleted)
            models.UniqueConstraint(
                fields=["user", "authcode"],
                condition=models.Q(
                    deleted_at__isnull=True,
                    credential_type="deployment_profile",
                ),
                name="unique_active_authcode_per_user",
            ),
            # User + folder + pin_id must be unique for SCM (for non-deleted)
            models.UniqueConstraint(
                fields=["user", "scm_folder_name", "scm_pin_id"],
                condition=models.Q(
                    deleted_at__isnull=True,
                    credential_type="scm",
                ),
                name="unique_active_scm_folder_pin_per_user",
            ),
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Store original values after loading from DB
        self._store_original_values()

    def __str__(self):
        """Return credential name (no sensitive data)."""
        return self.name

    def __repr__(self):
        """Return safe representation (no sensitive data)."""
        return f"<Credential(id={self.pk}, name='{self.name}', type='{self.credential_type}')>"

    def save(self, *args, **kwargs):
        """Save with validation.

        Logs DEBUG on successful save (create or update).
        Exceptions from validation or database are propagated, not swallowed.

        Raises:
            ValidationError: If validation fails
            DatabaseError: If database operation fails
        """
        is_create = self._is_new
        self.full_clean()
        super().save(*args, **kwargs)

        # Log success
        user_context = f"user_id={self.user_id}"
        if is_create:
            logger.debug(
                "Credential created: id=%s, %s, credential_type=%s, name='%s'",
                self.pk,
                user_context,
                self.credential_type,
                self.name,
            )
        else:
            logger.debug(
                "Credential updated: id=%s, %s, credential_type=%s, name='%s'",
                self.pk,
                user_context,
                self.credential_type,
                self.name,
            )

        # Update stored original values after save
        self._store_original_values()

    def refresh_from_db(self, using=None, fields=None, from_queryset=None):
        """Refresh and update original values."""
        super().refresh_from_db(using=using, fields=fields, from_queryset=from_queryset)
        self._store_original_values()

    def clean(self):
        """Validate the credential based on its type and state.

        Logs DEBUG on successful validation, ERROR on validation failure.

        Raises:
            ValidationError: If validation fails (with descriptive error messages)
        """
        errors = {}
        user_context = f"user_id={self.user_id}" if self.user_id else "user_id=None"

        # Validate name
        if not self.name:
            errors["name"] = "Name is required."
        elif not self.name.strip():
            errors["name"] = "Name cannot be whitespace only."

        # Validate credential_type
        if not self.credential_type:
            errors["credential_type"] = "Credential type is required."
        elif self.credential_type not in [c[0] for c in self.Type.choices]:
            errors["credential_type"] = f"'{self.credential_type}' is not a valid credential type."

        # Immutability checks (only for existing records)
        if not self._is_new:
            # Check credential_type immutability
            if self._original_credential_type and self.credential_type != self._original_credential_type:
                errors["credential_type"] = "Credential type cannot be changed after creation."

            # Check user immutability
            if self._original_user_id and self.user_id != self._original_user_id:
                errors["user"] = "User (ownership) cannot be changed after creation."

            # Check authcode immutability for deployment profiles
            if (
                self._original_credential_type == self.Type.DEPLOYMENT_PROFILE
                and self._original_authcode
                and self.authcode != self._original_authcode
            ):
                errors["authcode"] = "Authcode cannot be changed after creation."

            # Check undelete attempt
            if self._original_deleted_at is not None and self.deleted_at is None:
                errors["deleted_at"] = "Cannot undelete a credential."

            # Check modification of deleted credential
            # Only allow if nothing else changed. For simplicity, we reject any save
            # on deleted credentials (comparing all fields is complex)
            if (
                self._original_deleted_at is not None
                and self.deleted_at is not None
                and self.name != self._get_db_value("name")
            ):
                errors["name"] = "Cannot modify a deleted credential."

        # Type-specific validation (only if type is valid)
        if self.credential_type and self.credential_type in [c[0] for c in self.Type.choices]:
            if self.credential_type == self.Type.SCM:
                self._validate_scm_fields(errors)
            elif self.credential_type == self.Type.DEPLOYMENT_PROFILE:
                self._validate_deployment_profile_fields(errors)

        # Uniqueness validation (supplements DB constraints)
        if not errors:
            self._validate_uniqueness(errors)

        if errors:
            # Log ERROR with field names and user context
            field_names = ", ".join(errors.keys())
            logger.error(
                "Credential validation failed: fields=[%s], %s, credential_type=%s",
                field_names,
                user_context,
                self.credential_type or "None",
            )
            raise ValidationError(errors)

        # Log DEBUG on successful validation
        logger.debug(
            "Credential validation passed: %s, credential_type=%s, name='%s'",
            user_context,
            self.credential_type,
            self.name,
        )

    def _get_db_value(self, field_name: str):
        """Get the current database value for a field."""
        if not self.pk:
            return None
        try:
            db_instance = Credential.objects.get(pk=self.pk)
            return getattr(db_instance, field_name)
        except Credential.DoesNotExist:
            return None

    def _validate_scm_fields(self, errors: dict):
        """Validate SCM-specific fields."""
        if not self.scm_folder_name:
            errors["scm_folder_name"] = "SCM folder name is required for SCM credentials."
        elif not self.scm_folder_name.strip():
            errors["scm_folder_name"] = "SCM folder name cannot be whitespace only."

        if not self.scm_pin_id:
            errors["scm_pin_id"] = "SCM PIN ID is required for SCM credentials."
        elif not self.scm_pin_id.strip():
            errors["scm_pin_id"] = "SCM PIN ID cannot be whitespace only."

        if not self.scm_pin_value:
            errors["scm_pin_value"] = "SCM PIN value is required for SCM credentials."

        if not self.sls_region:
            errors["sls_region"] = "SLS region is required for SCM credentials."
        elif self.sls_region not in [c[0] for c in self.SLSRegion.choices]:
            errors["sls_region"] = f"'{self.sls_region}' is not a valid SLS region."

    def _validate_deployment_profile_fields(self, errors: dict):
        """Validate deployment profile-specific fields."""
        if not self.authcode:
            errors["authcode"] = "Authcode is required for deployment profiles."
        else:
            # Validate authcode format: letter followed by 7 digits
            if not re.match(r"^[A-Z][0-9]{7}$", self.authcode):
                errors["authcode"] = "Authcode must be a letter followed by 7 digits (e.g., D9232090)."

    def _validate_uniqueness(self, errors: dict):
        """Validate uniqueness constraints at application level.

        Supplements database constraints for early validation.
        Logs DEBUG for uniqueness checks performed.
        """
        if not self.user_id:
            logger.debug("Skipping uniqueness validation: no user_id set")
            return  # Can't check uniqueness without user

        # Build queryset for active credentials of same user (exclude self)
        qs = Credential.objects.filter(user_id=self.user_id, deleted_at__isnull=True)
        if self.pk:
            qs = qs.exclude(pk=self.pk)

        logger.debug(
            "Uniqueness check: user_id=%s, pk=%s, existing_count=%d",
            self.user_id,
            self.pk,
            qs.count(),
        )

        # Check unique name per user
        if self.name and qs.filter(name=self.name).exists():
            logger.debug(
                "Uniqueness violation: duplicate name '%s' for user_id=%s",
                self.name,
                self.user_id,
            )
            errors["name"] = f"A credential named '{self.name}' already exists."

        # Check unique authcode per user (for deployment profiles)
        # Note: authcode uses EncryptedCharField with Fernet (non-deterministic).
        # We must load records and compare decrypted values in Python.
        if self.credential_type == self.Type.DEPLOYMENT_PROFILE and self.authcode:
            existing_profiles = list(qs.filter(credential_type=self.Type.DEPLOYMENT_PROFILE))
            # Compare decrypted authcodes (field decrypts automatically on access)
            authcode_exists = any(p.authcode == self.authcode for p in existing_profiles)
            logger.debug(
                "Authcode uniqueness check: authcode=%s, type=%s, checked=%d, exists=%s",
                self.authcode[:4] + "****" if self.authcode else None,
                self.credential_type,
                len(existing_profiles),
                authcode_exists,
            )
            if authcode_exists:
                errors["authcode"] = "A deployment profile with this authcode already exists."

        # Check unique SCM folder+pin combo per user
        if self.credential_type == self.Type.SCM and self.scm_folder_name and self.scm_pin_id:
            scm_exists = qs.filter(
                credential_type=self.Type.SCM,
                scm_folder_name=self.scm_folder_name,
                scm_pin_id=self.scm_pin_id,
            ).exists()
            logger.debug(
                "SCM uniqueness check: folder=%s, pin_id=%s, exists=%s",
                self.scm_folder_name,
                self.scm_pin_id,
                scm_exists,
            )
            if scm_exists:
                errors["scm_folder_name"] = "An SCM credential with this folder and PIN ID already exists."

    def _store_original_values(self):
        """Store original values for immutability checks.

        Uses __dict__ access to avoid triggering deferred field loading,
        which would cause infinite recursion during Django's .only() queries.
        """
        if self.pk:
            self._is_new = False
            # Access via __dict__ to avoid triggering deferred field refresh
            self._original_credential_type = self.__dict__.get("credential_type")
            self._original_user_id = self.__dict__.get("user_id")
            self._original_authcode = self.__dict__.get("authcode", "")
            self._original_deleted_at = self.__dict__.get("deleted_at")
        else:
            self._is_new = True


class RangeInstance(models.Model):
    """Tracks hydrated scenario configs sent to engine.

    Uses integer IDs (not ForeignKeys) to decouple CMS from external models.
    See GH issue #446 for planned migration to use FK for agent_id after
    Asset/AgentConfig models are moved to CMS.

    Attributes:
        range_id: ID of the Range created by engine (IntegerField, not FK)
        scenario_id: Template name used (e.g., 'basic', 'ad_attack_lab')
        user_id: ID of the user who requested creation (IntegerField, not FK)
        agent_id: ID of the agent used, if any (IntegerField, nullable)
        created_at: When this record was created
    """

    range_id = models.IntegerField(unique=True)
    scenario_id = models.CharField(max_length=50)
    user_id = models.IntegerField()
    agent_id = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Range Instance"
        verbose_name_plural = "Range Instances"

    def __str__(self):
        return f"Range {self.range_id}: {self.scenario_id}"
