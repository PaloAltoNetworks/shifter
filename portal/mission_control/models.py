"""Mission Control models."""

from django.conf import settings
from django.db import models, transaction

from .fields import EncryptedCharField


class Asset(models.Model):
    """Abstract base class for user-owned assets.

    Provides common fields for all assets:
    - name: User-friendly identifier
    - created_at/deleted_at: Timestamps for lifecycle
    - is_deleted: Property for soft delete status
    - active_for_user(): Classmethod to filter active assets

    Note: user FK is defined in concrete classes to allow
    different related_name values per model type.
    """

    name = models.CharField(max_length=255, help_text="User-friendly name")
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True
        ordering = ["-created_at"]

    @property
    def is_deleted(self):
        """Return True if this asset has been soft-deleted."""
        return self.deleted_at is not None

    @classmethod
    def active_for_user(cls, user):
        """Return non-deleted assets for a user."""
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


class OperatingSystem(models.Model):
    """Reference table for supported operating systems."""

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
        """Find the OS that matches a given file extension."""
        ext = extension.lower()
        if not ext.startswith("."):
            ext = f".{ext}"
        for os in cls.objects.all():
            if ext in os.extensions:
                return os
        return None


class UserProfile(models.Model):
    """Extended user data for soft delete and anonymization."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
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
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"

    def __str__(self):
        return f"Profile for {self.user.email}"

    @property
    def is_deleted(self):
        return self.deleted_at is not None


class AgentConfig(FileAsset):
    """XDR/XSIAM agent installer uploaded by a user.

    Inherits from FileAsset:
    - name, created_at, deleted_at, is_deleted from Asset
    - s3_key, original_filename, file_size_bytes, sha256_hash, file_size_mb from FileAsset

    AgentConfig-specific:
    - user: Owner of this agent (with related_name="agents")
    - os: Operating system this agent is for
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agents",
    )
    os = models.ForeignKey(
        OperatingSystem,
        on_delete=models.PROTECT,
        related_name="agents",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Agent Config"
        verbose_name_plural = "Agent Configs"

    def __str__(self):
        return f"{self.name} ({self.os.name})"


class StrataConfig(models.Model):
    """Strata Cloud Manager configuration for NGFW instances.

    Stores SCM registration credentials for VM-Series bootstrap.
    Used to generate init-cfg.txt with PIN-based authentication.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="strata_configs",
    )
    name = models.CharField(
        max_length=255,
        help_text="User-friendly name for this config",
    )

    # SCM Registration fields
    scm_folder_name = models.CharField(
        max_length=255,
        help_text="SCM folder name (Configuration > Folders in SCM)",
    )
    scm_pin_id = models.CharField(
        max_length=255,
        help_text="Auto-registration PIN ID (Assets > Device Certificates in SCM)",
    )
    scm_pin_value = EncryptedCharField(
        max_length=255,
        help_text="Auto-registration PIN value (encrypted at rest)",
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Strata Config"
        verbose_name_plural = "Strata Configs"

    def __str__(self):
        return f"{self.name} ({self.scm_folder_name})"

    @property
    def is_deleted(self):
        """Return True if this config has been soft-deleted."""
        return self.deleted_at is not None

    @classmethod
    def active_for_user(cls, user):
        """Return non-deleted Strata configs for a user."""
        return cls.objects.filter(user=user, deleted_at__isnull=True)

    def get_init_cfg_context(self) -> dict:
        """Get context dict for init-cfg.txt template rendering.

        Returns:
            Dict with pin_id, pin_value, folder_name keys for template.
        """
        return {
            "pin_id": self.scm_pin_id,
            "pin_value": self.scm_pin_value,
            "folder_name": self.scm_folder_name,
        }

    def clean(self):
        """Validate that required fields are not empty strings."""
        from django.core.exceptions import ValidationError

        errors = {}
        if not self.scm_folder_name or not self.scm_folder_name.strip():
            errors["scm_folder_name"] = "SCM folder name cannot be empty."
        if not self.scm_pin_id or not self.scm_pin_id.strip():
            errors["scm_pin_id"] = "SCM PIN ID cannot be empty."
        if not self.scm_pin_value or not self.scm_pin_value.strip():
            errors["scm_pin_value"] = "SCM PIN value cannot be empty."

        if errors:
            raise ValidationError(errors)


class Range(models.Model):
    """User's cyber range instance with lifecycle management."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROVISIONING = "provisioning", "Provisioning"
        READY = "ready", "Ready"
        PAUSED = "paused", "Paused"
        RESUMING = "resuming", "Resuming"
        DESTROYING = "destroying", "Destroying"
        DESTROYED = "destroyed", "Destroyed"
        FAILED = "failed", "Failed"

    # Status groupings for lifecycle management (defined after Status for reference)
    ACTIVE_STATUSES: frozenset[str]  # User has a "live" range, can't launch another
    DESTROYABLE_STATUSES: frozenset[str]  # Range can be destroyed
    TERMINAL_STATUSES: frozenset[str]  # Range has reached end of lifecycle
    CANCELLABLE_STATUSES: frozenset[str]  # Range can be cancelled (early lifecycle only)

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ranges")
    agent = models.ForeignKey(
        AgentConfig,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ranges",
        help_text="Agent for victim instances",
    )
    dc_agent = models.ForeignKey(
        AgentConfig,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dc_ranges",
        help_text="Agent for DC instances (Windows only, required for AD scenarios)",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    # AWS resource IDs (populated by provisioner Lambda)
    subnet_id = models.CharField(max_length=50, blank=True, default="", help_text="AWS subnet ID (e.g., subnet-abc123)")
    subnet_cidr = models.CharField(max_length=18, blank=True, default="", help_text="Subnet CIDR (e.g., 10.1.5.0/24)")
    subnet_index = models.PositiveIntegerField(null=True, blank=True, help_text="Unique index for CIDR allocation")
    victim_ip = models.GenericIPAddressField(null=True, blank=True)
    victim_instance_id = models.CharField(
        max_length=50, blank=True, default="", help_text="EC2 instance ID (e.g., i-abc123)"
    )
    kali_ip = models.GenericIPAddressField(null=True, blank=True)
    kali_instance_id = models.CharField(
        max_length=50, blank=True, default="", help_text="Kali EC2 instance ID (e.g., i-abc123)"
    )
    kali_ssh_key_secret_arn = models.CharField(
        max_length=500, blank=True, default="", help_text="Secrets Manager ARN for Kali SSH private key"
    )
    victim_ssh_key_secret_arn = models.CharField(
        max_length=500, blank=True, default="", help_text="Secrets Manager ARN for Victim SSH private key"
    )
    chat_url = models.URLField(max_length=500, blank=True, default="")

    # Step Functions tracking
    step_function_execution_arn = models.CharField(
        max_length=500, blank=True, default="", help_text="Step Functions execution ARN"
    )

    # Shifter Engine fields (v2)
    instance_config = models.JSONField(
        null=True,
        blank=True,
        help_text="JSON array of instance configurations for Shifter Engine",
    )
    provisioned_instances = models.JSONField(
        null=True,
        blank=True,
        help_text="JSON array of provisioned instance details from Pulumi",
    )
    pulumi_stack = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Pulumi stack name for this range",
    )
    provisioner_version = models.CharField(
        max_length=10,
        default="v1",
        help_text="Provisioner version: v1=Lambda, v2=Pulumi",
    )

    # NGFW (VM-Series) fields
    ngfw_enabled = models.BooleanField(default=False, help_text="Deploy VM-Series NGFW inline between Kali and Victim")
    strata_config = models.ForeignKey(
        StrataConfig,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ranges",
        help_text="SCM config for NGFW bootstrap (PIN-based registration)",
    )
    ngfw_instance_id = models.CharField(max_length=50, blank=True, default="", help_text="NGFW EC2 instance ID")
    ngfw_untrust_ip = models.GenericIPAddressField(
        null=True, blank=True, help_text="NGFW untrust interface IP (Kali-facing)"
    )
    ngfw_trust_ip = models.GenericIPAddressField(
        null=True, blank=True, help_text="NGFW trust interface IP (Victim-facing)"
    )

    # Status and timestamps
    error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    paused_at = models.DateTimeField(null=True, blank=True)
    destroyed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        agent_name = self.agent.name if self.agent else "Unknown Agent"
        return f"Range {self.id} ({agent_name}) - {self.status}"

    @property
    def is_active(self):
        """Return True if range is in an active/usable state."""
        return self.status in (self.Status.READY, self.Status.PAUSED)

    @property
    def is_terminal(self):
        """Return True if range has reached a final state."""
        return self.status in self.TERMINAL_STATUSES

    @classmethod
    def get_active_for_user(cls, user):
        """Return the user's active range, or None.

        DESTROYING ranges are excluded - user can launch a new range while
        the old one is being cleaned up (subnet allocation handles the race).
        """
        return cls.objects.filter(user=user, status__in=cls.ACTIVE_STATUSES).first()

    @classmethod
    def get_destroyable_for_user(cls, user):
        """Return a range that can be destroyed (active or failed), or None."""
        return cls.objects.filter(user=user, status__in=cls.DESTROYABLE_STATUSES).first()

    # Subnet index allocation constants
    # Range VPC uses 10.1.0.0/16, each range gets 10.1.{index}.0/24
    # Reserve index 0 (network) and 255 (broadcast), use 1-254
    SUBNET_INDEX_MIN = 1
    SUBNET_INDEX_MAX = 254

    @classmethod
    def allocate_subnet_index(cls) -> int:
        """
        Allocate the next available subnet index for a new range.

        Uses SELECT FOR UPDATE to prevent race conditions when multiple
        ranges are being created concurrently.

        Returns:
            int: The allocated subnet index (1-254)

        Raises:
            ValueError: If no subnet indices are available (254 active ranges)
        """
        with transaction.atomic():
            # Lock rows to prevent race conditions
            # Get all subnet_index values currently in use by active ranges
            # Exclude terminal states - those ranges don't have AWS resources
            used_indices = set(
                cls.objects.select_for_update()
                .exclude(status__in=cls.TERMINAL_STATUSES)
                .exclude(subnet_index__isnull=True)
                .values_list("subnet_index", flat=True)
            )

            # Find the first available index
            for index in range(cls.SUBNET_INDEX_MIN, cls.SUBNET_INDEX_MAX + 1):
                if index not in used_indices:
                    return index

            raise ValueError(
                f"No subnet indices available. Maximum {cls.SUBNET_INDEX_MAX} "
                "concurrent ranges supported. Destroy some ranges first."
            )

    def get_instance_by_role(self, role: str) -> dict | None:
        """Get instance details by role.

        Args:
            role: Instance role ("attacker" or "victim")

        Returns:
            Dictionary with instance details or None if not found
        """
        if not self.provisioned_instances:
            return None
        for instance in self.provisioned_instances:
            if instance.get("role") == role:
                return instance
        return None

    @property
    def attacker_instance(self) -> dict | None:
        """Get the attacker instance details."""
        return self.get_instance_by_role("attacker")

    @property
    def victim_instances(self) -> list:
        """Get all victim instance details.

        Returns:
            List of victim instance dictionaries
        """
        if not self.provisioned_instances:
            return []
        return [i for i in self.provisioned_instances if i.get("role") == "victim"]

    @property
    def kali_private_ip(self) -> str | None:
        """Get the Kali (attacker) instance private IP address.

        Returns:
            The private IP address string or None if not available
        """
        attacker = self.attacker_instance
        if not attacker:
            return None
        return attacker.get("private_ip")

    @property
    def victim_private_ip(self) -> str | None:
        """Get the first victim instance private IP address.

        Returns:
            The private IP address string or None if not available
        """
        victims = self.victim_instances
        if not victims:
            return None
        return victims[0].get("private_ip")


# Assign status groupings after class definition (can't reference Status inside class body)
Range.ACTIVE_STATUSES = frozenset(
    {
        Range.Status.PENDING,
        Range.Status.PROVISIONING,
        Range.Status.READY,
        Range.Status.PAUSED,
        Range.Status.RESUMING,
    }
)
Range.DESTROYABLE_STATUSES = frozenset(
    {
        Range.Status.PENDING,
        Range.Status.PROVISIONING,
        Range.Status.READY,
        Range.Status.PAUSED,
        Range.Status.RESUMING,
        Range.Status.FAILED,
    }
)
Range.TERMINAL_STATUSES = frozenset(
    {
        Range.Status.DESTROYED,
        Range.Status.FAILED,
    }
)
Range.CANCELLABLE_STATUSES = frozenset(
    {
        Range.Status.PENDING,
        Range.Status.PROVISIONING,
    }
)


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
