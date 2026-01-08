"""CMS models - Asset hierarchy and content management models."""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import models
from django.utils import timezone

from shared.enums import RequestType

# CredentialBase is defined locally below (migrated from mission_control)

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Abstract Base Models
# -----------------------------------------------------------------------------


class CatalogBase(models.Model):
    """Abstract base for catalog entities (system-defined types).

    Catalog entities are reference data that define available types,
    not user-owned instances. Examples: CredentialType, ScenarioType.

    Subclasses should define a `spec_class` CharField pointing to
    the Pydantic spec class for validation.

    Attributes:
        name: Human-readable name for display.
        slug: URL-safe identifier for lookups.
        created_at: When this catalog entry was created.
    """

    name = models.CharField(max_length=100, help_text="Display name")
    slug = models.SlugField(max_length=50, unique=True, help_text="URL-safe identifier")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True

    def __str__(self):
        return self.name

    def get_spec_class(self):
        """Load and return the Pydantic spec class.

        Requires subclass to define a `spec_class` CharField.

        Returns:
            The Pydantic model class for validating data.

        Raises:
            AttributeError: If subclass doesn't define spec_class.
            ImportError: If the spec_class path is invalid.
        """
        from importlib import import_module

        module_path, class_name = self.spec_class.rsplit(".", 1)
        module = import_module(module_path)
        return getattr(module, class_name)

    def validate_data(self, data: dict) -> dict:
        """Validate data against this type's spec.

        Args:
            data: Raw data to validate.

        Returns:
            Validated and normalized data dict.

        Raises:
            pydantic.ValidationError: If data doesn't match the spec.
        """
        spec_class = self.get_spec_class()
        validated = spec_class.model_validate(data)
        return validated.model_dump()


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
    - sha256_hash: Content hash (optional, for future server-side compute)
    """

    s3_key = models.CharField(max_length=500, help_text="S3 object key")
    original_filename = models.CharField(max_length=255)
    file_size_bytes = models.PositiveBigIntegerField()
    sha256_hash = models.CharField(max_length=64, blank=True, default="")

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

    @property
    def expires_soon(self):
        """Return True if this credential expires within 30 days."""
        if not self.expires_at:
            return False
        if self.is_expired:
            return False
        return self.expires_at <= timezone.now() + timezone.timedelta(days=30)


# -----------------------------------------------------------------------------
# Reference Models
# -----------------------------------------------------------------------------


class OperatingSystem(models.Model):
    """Reference table for supported operating systems.

    Used for categorizing file assets by their target platform.
    """

    slug = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    extensions = models.JSONField(
        default=list, help_text="File extensions that map to this OS (e.g., ['.msi'])"
    )

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


class CredentialType(CatalogBase):
    """Catalog of credential types.

    Type Object pattern: types are data rows, not code enums.
    Each row defines a credential type and points to its Pydantic spec class.

    Attributes (inherited from CatalogBase):
        name: Display name (e.g., "SCM Registration").
        slug: Lookup key (e.g., "scm").
        created_at: When this type was added.
        get_spec_class(): Load the Pydantic spec class.
        validate_data(): Validate data against the spec.

    Attributes:
        spec_class: Dotted path to the Pydantic spec class for validation.
    """

    spec_class = models.CharField(
        max_length=255,
        help_text="Dotted path to Pydantic spec class (e.g., 'shared.schemas.SCMCredentialSpec')",
    )

    class Meta:
        verbose_name = "Credential Type"
        verbose_name_plural = "Credential Types"


class Credential(models.Model):
    """User's credential instance.

    Stores user credentials with type-specific data in a JSON field.
    Validation is delegated to Pydantic spec classes referenced by CredentialType.

    Attributes:
        name: User-friendly name for this credential.
        user: Owner of this credential.
        credential_type: FK to CredentialType catalog.
        data: Type-specific fields as JSON (validated by spec_class).
        created_at: When this credential was created.
        expires_at: When this credential expires (optional).
        deleted_at: Soft delete timestamp (None = active).
    """

    name = models.CharField(max_length=100, help_text="User-friendly name")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="credentials",
    )
    credential_type = models.ForeignKey(
        CredentialType,
        on_delete=models.PROTECT,
        related_name="credentials",
    )
    data = models.JSONField(
        default=dict,
        help_text="Type-specific credential data (validated by spec_class)",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Credential"
        verbose_name_plural = "Credentials"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"],
                condition=models.Q(deleted_at__isnull=True),
                name="unique_active_credential_name_per_user",
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def is_deleted(self):
        """Return True if this credential has been soft-deleted."""
        return self.deleted_at is not None

    @property
    def is_expired(self):
        """Return True if this credential has expired."""
        if not self.expires_at:
            return False
        return timezone.now() > self.expires_at

    @property
    def expires_soon(self):
        """Return True if this credential expires within 30 days."""
        if not self.expires_at:
            return False
        if self.is_expired:
            return False
        return self.expires_at <= timezone.now() + timezone.timedelta(days=30)


# -----------------------------------------------------------------------------
# Instance Models
# -----------------------------------------------------------------------------


class InstanceType(CatalogBase):
    """Catalog of instance types (container, vm, etc).

    Type Object pattern: types are data rows, not code enums.
    Each row defines an instance type and points to its Pydantic spec class.

    Attributes (inherited from CatalogBase):
        name: Display name (e.g., "Container").
        slug: Lookup key (e.g., "container").
        created_at: When this type was added.
        get_spec_class(): Load the Pydantic spec class.
        validate_data(): Validate data against the spec.

    Attributes:
        spec_class: Dotted path to the Pydantic spec class for validation.
    """

    spec_class = models.CharField(
        max_length=255,
        help_text="Dotted path to Pydantic spec class",
    )

    class Meta:
        verbose_name = "Instance Type"
        verbose_name_plural = "Instance Types"


class Instance(models.Model):
    """Instance definition.

    Stores instance config with type-specific data in a JSON field.
    Validation is delegated to Pydantic spec classes referenced by InstanceType.

    Attributes:
        name: User-friendly name for this instance.
        instance_type: FK to InstanceType catalog.
        data: Type-specific fields as JSON (validated by spec_class).
        created_at: When this instance was created.
        deleted_at: Soft delete timestamp (None = active).
    """

    name = models.CharField(max_length=100, help_text="User-friendly name")
    instance_type = models.ForeignKey(
        InstanceType,
        on_delete=models.PROTECT,
        related_name="instances",
    )
    data = models.JSONField(
        default=dict,
        help_text="Type-specific instance data (validated by spec_class)",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Instance"
        verbose_name_plural = "Instances"

    def __str__(self):
        return self.name

    @property
    def is_deleted(self):
        """Return True if this instance has been soft-deleted."""
        return self.deleted_at is not None


# -----------------------------------------------------------------------------
# App Models
# -----------------------------------------------------------------------------


class AppType(CatalogBase):
    """Catalog of app types (os, ngfw, agent, other).

    Type Object pattern: types are data rows, not code enums.
    Each row defines an app type and points to its Pydantic spec class.

    Attributes:
        name: Display name (inherited from CatalogBase).
        slug: URL-safe identifier (inherited from CatalogBase).
        spec_class: Dotted path to Pydantic spec class.
    """

    spec_class = models.CharField(
        max_length=255,
        help_text="Dotted path to Pydantic spec class",
    )

    class Meta:
        verbose_name = "App Type"
        verbose_name_plural = "App Types"


class App(models.Model):
    """App definition tied to instances.

    Stores app config with type-specific data in a JSON field.
    Validation is delegated to Pydantic spec classes referenced by AppType.

    Attributes:
        name: User-friendly name for this app.
        app_type: FK to AppType catalog.
        data: Type-specific fields as JSON (validated by spec_class).
        created_at: When this app was created.
        deleted_at: Soft delete timestamp (None = active).
    """

    name = models.CharField(max_length=100, help_text="User-friendly name")
    app_type = models.ForeignKey(
        AppType,
        on_delete=models.PROTECT,
        related_name="apps",
    )
    data = models.JSONField(
        default=dict,
        help_text="Type-specific app data (validated by spec_class)",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "App"
        verbose_name_plural = "Apps"

    def __str__(self):
        return self.name

    @property
    def is_deleted(self):
        """Return True if this app has been soft-deleted."""
        return self.deleted_at is not None


# -----------------------------------------------------------------------------
# Agent Models
# -----------------------------------------------------------------------------


class AgentConfig(FileAsset):
    """XDR/XSIAM agent installer uploaded by a user.

    Inherits from FileAsset:
    - name, created_at, deleted_at, is_deleted from Asset
    - s3_key, original_filename, file_size_bytes, sha256_hash, file_size_mb from FileAsset

    AgentConfig-specific:
    - user: Owner of this agent (with related_name="cms_agents")
    - os: Operating system this agent is for
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="cms_agents",
    )
    os = models.ForeignKey(
        OperatingSystem,
        on_delete=models.PROTECT,
        related_name="cms_agents",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Agent Config"
        verbose_name_plural = "Agent Configs"

    def __str__(self):
        return f"{self.name} ({self.os.name})"


# -----------------------------------------------------------------------------
# Request Tracking
# -----------------------------------------------------------------------------


class Request(models.Model):
    """Provisioning request container.

    Groups items requested together while allowing independent lifecycles.
    Maps 1:1 with RequestSpec schema.

    Attributes:
        request_id: UUID identifier for this request (correlation key).
        user: User who made the request.
        created_at: When the request was created.
        deleted_at: Soft delete timestamp (None = active).
    """

    request_id = models.UUIDField(unique=True, db_index=True)
    request_type = models.CharField(
        max_length=20,
        choices=[(t.value, t.name) for t in RequestType],
        db_index=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="requests",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Request"
        verbose_name_plural = "Requests"

    def __str__(self):
        return f"Request {self.request_id}"

    @property
    def is_deleted(self):
        """Return True if this request has been soft-deleted."""
        return self.deleted_at is not None


# -----------------------------------------------------------------------------
# Range Instance Tracking
# -----------------------------------------------------------------------------


class NGFW(Asset):
    """NGFW configuration owned by a user.

    CMS owns the logical NGFW asset - what the user asked for.
    Engine owns the infrastructure state - AWS resources, IPs, etc.

    Status is synced from Engine via pub/sub events (like RangeInstance).
    ngfw_spec stores the hydrated configuration sent to Engine.

    Note: Uses legacy table name for migration compatibility.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ngfws",
    )
    request = models.ForeignKey(
        Request,
        on_delete=models.CASCADE,
        related_name="ngfws",
        null=True,
        blank=True,
    )
    # Hydrated configuration sent to Engine (credentials, registration method, etc.)
    ngfw_spec = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "NGFW"
        verbose_name_plural = "NGFWs"
        db_table = "mission_control_userngfw"  # Keep for migration compatibility


class ActiveRangeInstanceManager(models.Manager):
    """Manager that filters out soft-deleted RangeInstances."""

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class RangeInstance(models.Model):
    """Tracks hydrated scenario configs sent to engine.

    After GH issue #446:
    - agent is now FK to AgentConfig (nullable, SET_NULL on delete)
    - range_id remains IntegerField (CMS doesn't own Range model)
    - user_id remains IntegerField (CMS doesn't own User model)

    After GH issue #452:
    - status tracks CMS's view of range lifecycle (from pub/sub events)
    - deleted_at enables soft deletion for history preservation

    Invariant: Terminal statuses (DESTROYED, FAILED) automatically set deleted_at.
    This is enforced in save() to prevent orphaned terminal records.

    Attributes:
        range_id: ID of the Range created by engine (IntegerField, not FK)
        scenario_id: Template name used (e.g., 'basic', 'ad_attack_lab')
        user_id: ID of the user who requested creation (IntegerField, not FK)
        agent: AgentConfig used, if any (FK, nullable)
        status: Current lifecycle status (pending, provisioning, ready, etc.)
        range_spec: Hydrated RangeSpec JSON (instance specs, scenario details)
        created_at: When this record was created
        deleted_at: When this record was soft-deleted (null if active)
    """

    range_id = models.IntegerField(unique=True)
    scenario_id = models.CharField(max_length=50)
    user_id = models.IntegerField()
    agent = models.ForeignKey(
        AgentConfig,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="range_instances",
    )
    status = models.CharField(max_length=20, default="pending")
    range_spec = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    # Managers
    objects = models.Manager()
    active = ActiveRangeInstanceManager()

    class Meta:
        verbose_name = "Range Instance"
        verbose_name_plural = "Range Instances"

    def __str__(self):
        return f"Range {self.range_id}: {self.scenario_id}"

    def save(self, *args, **kwargs):
        """Save with terminal status invariant enforcement.

        When status is set to a terminal value (DESTROYED, FAILED),
        deleted_at is automatically set if not already set.

        If update_fields is specified and we set deleted_at, we add it
        to update_fields to ensure it's persisted.
        """
        from shared.enums import TERMINAL_STATUSES

        # Enforce invariant: terminal status → soft delete
        terminal_values = {s.value for s in TERMINAL_STATUSES}
        if self.status in terminal_values and self.deleted_at is None:
            self.deleted_at = timezone.now()
            logger.debug(
                "RangeInstance %s: auto-setting deleted_at due to terminal status %s",
                self.range_id,
                self.status,
            )

            # If update_fields is specified, add deleted_at to ensure it's saved
            update_fields = kwargs.get("update_fields")
            if update_fields is not None and "deleted_at" not in update_fields:
                kwargs["update_fields"] = [*list(update_fields), "deleted_at"]

        super().save(*args, **kwargs)
