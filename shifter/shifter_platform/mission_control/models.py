"""Mission Control models."""

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

# OperatingSystem has been moved to cms.models
# See: cms/migrations/0004_move_operatingsystem_to_cms.py


class Asset(models.Model):
    """Abstract base for user-owned assets with soft delete."""

    name = models.CharField(max_length=100, help_text="User-friendly name")
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    def __str__(self):
        return self.name

    @property
    def is_deleted(self):
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


class Credential(Asset):
    """Abstract base for credential assets with expiration tracking."""

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
        if not self.expires_at:
            return False
        return timezone.now() > self.expires_at


# Note: SCMCredential and NGFWDeploymentProfile have been migrated to cms.Credential.
# See cms/models.py for the unified Credential model.


class UserNGFW(Asset):
    """Persistent NGFW instance. Users can have multiple."""

    class Status(models.TextChoices):
        NOT_PROVISIONED = "not_provisioned", "Not Provisioned"
        PROVISIONING = "provisioning", "Provisioning"
        READY = "ready", "Ready"
        STARTING = "starting", "Starting"
        ACTIVE = "active", "Active"
        STOPPING = "stopping", "Stopping"
        STOPPED = "stopped", "Stopped"
        DEPROVISIONING = "deprovisioning", "Deprovisioning"
        FAILED = "failed", "Failed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ngfws",
    )

    # Note: Credentials are managed by CMS, not stored here.
    # Engine receives hydrated config with decrypted values at provisioning time.
    # CMS tracks credential→range associations if needed.

    # Lifecycle
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.NOT_PROVISIONED,
    )

    # AWS Resources - NGFW
    instance_id = models.CharField(max_length=32, blank=True)
    mgmt_eni_id = models.CharField(max_length=32, blank=True)
    data_eni_id = models.CharField(max_length=32, blank=True)
    management_ip = models.GenericIPAddressField(null=True, blank=True)
    dataplane_ip = models.GenericIPAddressField(null=True, blank=True)

    # AWS Resources - GWLB
    gwlb_arn = models.CharField(max_length=256, blank=True)
    target_group_arn = models.CharField(max_length=256, blank=True)
    gwlb_service_name = models.CharField(max_length=256, blank=True)

    # PAN-OS Info
    serial_number = models.CharField(max_length=32, blank=True)
    device_cert_status = models.CharField(max_length=32, blank=True)
    xdr_configured = models.BooleanField(default=False)

    # Timestamps (beyond Asset's created_at, deleted_at)
    provisioned_at = models.DateTimeField(null=True, blank=True)
    last_started_at = models.DateTimeField(null=True, blank=True)
    last_stopped_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "User NGFW"
        verbose_name_plural = "User NGFWs"


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
        "cms.OperatingSystem",
        on_delete=models.PROTECT,
        related_name="agents",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Agent Config"
        verbose_name_plural = "Agent Configs"

    def __str__(self):
        return f"{self.name} ({self.os.name})"


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

    # Status groupings for lifecycle queries
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
    ngfw = models.ForeignKey(
        "UserNGFW",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ranges",
        help_text="Persistent NGFW instance for this range",
    )
    gwlb_endpoint_id = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text="GWLB endpoint ID for this range's NGFW",
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

    @property
    def standup_duration(self):
        """Total time from creation to ready.

        Returns:
            timedelta if both created_at and ready_at are set, None otherwise
        """
        if self.ready_at and self.created_at:
            return self.ready_at - self.created_at
        return None

    @classmethod
    def get_active_for_user(cls, user):
        """Return the user's active range, or None.

        DESTROYING ranges are excluded - user can launch a new range while
        the old one is being cleaned up (subnet allocation handles the race).
        """
        return cls.objects.filter(
            user=user,
            status__in=[
                cls.Status.PENDING,
                cls.Status.PROVISIONING,
                cls.Status.READY,
                cls.Status.PAUSED,
                cls.Status.RESUMING,
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
            # Get all subnet_index values currently in use by active ranges
            # Exclude terminal states (DESTROYED, FAILED) - those ranges don't have
            # AWS resources or their resources are being cleaned up
            used_indices = set(
                cls.objects.select_for_update()
                .exclude(status__in=[cls.Status.DESTROYED, cls.Status.FAILED])
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


# Define Range status groupings (after class definition to reference Status enum)
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
