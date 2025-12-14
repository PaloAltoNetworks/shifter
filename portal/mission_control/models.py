"""Mission Control models."""

from django.conf import settings
from django.db import models, transaction


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


class AgentConfig(models.Model):
    """XDR/XSIAM agent installer uploaded by a user."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="agents")
    os = models.ForeignKey(OperatingSystem, on_delete=models.PROTECT, related_name="agents")
    name = models.CharField(max_length=100, help_text="User-friendly name for this agent")
    s3_key = models.CharField(max_length=500, help_text="S3 object key for the installer")
    original_filename = models.CharField(max_length=255)
    file_size_bytes = models.PositiveBigIntegerField()
    sha256_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Agent Config"
        verbose_name_plural = "Agent Configs"

    def __str__(self):
        return f"{self.name} ({self.os.name})"

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    @property
    def file_size_mb(self):
        """Return file size in megabytes, rounded to 1 decimal."""
        return round(self.file_size_bytes / (1024 * 1024), 1)

    @classmethod
    def active_for_user(cls, user):
        """Return non-deleted agents for a user."""
        return cls.objects.filter(user=user, deleted_at__isnull=True)


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

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ranges")
    agent = models.ForeignKey(
        AgentConfig,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ranges",
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
    chat_url = models.URLField(max_length=500, blank=True, default="")

    # Step Functions tracking
    step_function_execution_arn = models.CharField(
        max_length=500, blank=True, default="", help_text="Step Functions execution ARN"
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
        return self.status in (self.Status.DESTROYED, self.Status.FAILED)

    @classmethod
    def get_active_for_user(cls, user):
        """Return the user's active range, or None.

        Includes DESTROYING to prevent launching a new range while one is being torn down.
        """
        return cls.objects.filter(
            user=user,
            status__in=[
                cls.Status.PENDING,
                cls.Status.PROVISIONING,
                cls.Status.READY,
                cls.Status.PAUSED,
                cls.Status.RESUMING,
                cls.Status.DESTROYING,
            ],
        ).first()

    @classmethod
    def get_destroyable_for_user(cls, user):
        """Return a range that can be destroyed (active or failed), or None."""
        return cls.objects.filter(
            user=user,
            status__in=[
                cls.Status.PENDING,
                cls.Status.PROVISIONING,
                cls.Status.READY,
                cls.Status.PAUSED,
                cls.Status.RESUMING,
                cls.Status.FAILED,
            ],
        ).first()

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
            # Get all subnet_index values currently in use by non-destroyed ranges
            used_indices = set(
                cls.objects.select_for_update()
                .exclude(status=cls.Status.DESTROYED)
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
