"""Engine models.

Infrastructure lifecycle models for Shifter platform.

- Request: Provisioning request container (1:1 with RequestSpec)
- Instantiation: Abstract base for materialized specs
- Range: User's cyber range instance with provisioned infrastructure
- NGFW: User's Next-Generation Firewall with AWS resources
- SubnetAllocation: CIDR reservation to prevent race conditions during provisioning
"""

import uuid

from django.conf import settings
from django.db import models, transaction

from shared.enums import RequestType


class Request(models.Model):
    """Provisioning request container.

    Groups items requested together while allowing independent lifecycles.
    Maps 1:1 with RequestSpec schema.

    Engine owns its own Request record - separate from CMS's Request.
    Correlation is via request_id UUID.

    Attributes:
        request_id: UUID identifier for this request (correlation key).
        user: User who made the request.
        created_at: When the request was created.
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
        related_name="engine_requests",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Request"
        verbose_name_plural = "Requests"

    def __str__(self):
        return f"Request {self.request_id}"


class Instantiation(models.Model):
    """Abstract base for any materialized spec.

    Provides common fields for tracking lifecycle of specs that have been
    interpreted into concrete infrastructure or behavior.

    Attributes:
        uuid: The UUID from the spec being instantiated (instance uuid, range uuid,
            app uuid, etc). This is the correlation key for events, WebSocket
            subscriptions, and linking to Terraform/Pulumi outputs.
        request: The request that spawned this instantiation.
        spec: The hydrated spec JSON (what was asked for).
        status: Current lifecycle status.
        created_at: When this was instantiated.
        deleted_at: When removal was requested (soft delete).
        destroyed_at: When infrastructure was actually torn down.
    """

    uuid = models.UUIDField(unique=True, db_index=True, default=uuid.uuid4, help_text="UUID from the spec")
    request = models.ForeignKey(
        Request,
        on_delete=models.CASCADE,
        related_name="%(class)s_instantiations",
        null=True,
        blank=True,
    )
    spec = models.JSONField(
        null=True,
        blank=True,
        help_text="Hydrated spec JSON from CMS (what was asked for)",
    )
    state = models.JSONField(
        null=True,
        blank=True,
        help_text="Infrastructure state (resource IDs, IPs, etc.)",
    )
    status = models.CharField(max_length=20, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    destroyed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    @property
    def is_deleted(self) -> bool:
        """Return True if removal has been requested."""
        return self.deleted_at is not None

    @property
    def is_destroyed(self) -> bool:
        """Return True if infrastructure has been torn down."""
        return self.destroyed_at is not None


class Instance(Instantiation):
    """Materialized InstanceSpec - compute resource.

    Represents an EC2 instance, container, or other compute unit.
    Apps run on Instances (1:N relationship).

    Attributes:
        role: Instance role from InstanceSpec (attacker, victim, dc, ngfw).
        os_type: Operating system type (kali, ubuntu, windows, panos).
    """

    class Role(models.TextChoices):
        ATTACKER = "attacker", "Attacker"
        VICTIM = "victim", "Victim"
        DC = "dc", "Domain Controller"
        NGFW = "ngfw", "NGFW"

    class OSType(models.TextChoices):
        KALI = "kali", "Kali Linux"
        UBUNTU = "ubuntu", "Ubuntu"
        WINDOWS = "windows", "Windows"
        PANOS = "panos", "PAN-OS"

    role = models.CharField(max_length=20, choices=Role.choices, db_index=True)
    os_type = models.CharField(max_length=20, choices=OSType.choices)
    subnet = models.ForeignKey(
        "Subnet",
        on_delete=models.CASCADE,
        related_name="instances",
        null=True,
        blank=True,
        help_text="Logical subnet this instance belongs to",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Instance"
        verbose_name_plural = "Instances"

    def __str__(self):
        return f"Instance {self.uuid} ({self.role}/{self.os_type})"


class App(Instantiation):
    """Materialized AppSpec - application running on compute.

    Represents an app (NGFW, Agent, OS, Other) that runs on an Instance.
    Child of Instance - mirrors the spec nesting.

    Attributes:
        app_type: App type discriminator (os, ngfw, agent, other).
        instance: Parent Instance this App runs on.
    """

    class AppType(models.TextChoices):
        OS = "os", "OS"
        NGFW = "ngfw", "NGFW"
        AGENT = "agent", "Agent"
        OTHER = "other", "Other"

    app_type = models.CharField(max_length=20, choices=AppType.choices, db_index=True)
    instance = models.ForeignKey(
        Instance,
        on_delete=models.CASCADE,
        related_name="apps",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "App"
        verbose_name_plural = "Apps"

    def __str__(self):
        return f"App {self.uuid} ({self.app_type})"


class Range(models.Model):
    """User's cyber range instance with lifecycle management."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROVISIONING = "provisioning", "Provisioning"
        READY = "ready", "Ready"
        PAUSING = "pausing", "Pausing"
        PAUSED = "paused", "Paused"
        RESUMING = "resuming", "Resuming"
        DESTROYING = "destroying", "Destroying"
        DESTROYED = "destroyed", "Destroyed"
        FAILED = "failed", "Failed"

    uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        help_text="Unique identifier for cross-service correlation",
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ranges")
    request = models.ForeignKey(
        Request,
        on_delete=models.CASCADE,
        related_name="ranges",
        null=True,
        blank=True,
        help_text="Request that spawned this range (new pattern)",
    )
    cms_user_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="User ID from CMS (may differ from Django user.id)",
    )
    ngfw_instance = models.ForeignKey(
        "Instance",
        on_delete=models.SET_NULL,
        related_name="attached_ranges",
        null=True,
        blank=True,
        help_text="NGFW Instance this range is attached to (for egress filtering)",
    )
    gwlb_endpoint_id = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text="GWLB endpoint ID for this range's NGFW (AWS resource ID)",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    # AWS resource IDs (populated by provisioner Lambda)
    subnet_id = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="AWS subnet ID (e.g., subnet-abc123)",
    )
    subnet_cidr = models.CharField(
        max_length=18,
        blank=True,
        default="",
        help_text="Subnet CIDR (e.g., 10.1.5.0/24)",
    )
    subnet_index = models.PositiveIntegerField(null=True, blank=True, help_text="Unique index for CIDR allocation")
    victim_ip = models.GenericIPAddressField(null=True, blank=True)
    victim_instance_id = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="EC2 instance ID (e.g., i-abc123)",
    )
    kali_ip = models.GenericIPAddressField(null=True, blank=True)
    kali_instance_id = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="Kali EC2 instance ID (e.g., i-abc123)",
    )
    kali_ssh_key_secret_arn = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Secrets Manager ARN for Kali SSH private key",
    )
    victim_ssh_key_secret_arn = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Secrets Manager ARN for Victim SSH private key",
    )
    chat_url = models.URLField(max_length=500, blank=True, default="")

    # Step Functions tracking
    step_function_execution_arn = models.CharField(
        max_length=500, blank=True, default="", help_text="Step Functions execution ARN"
    )

    # Shifter Engine fields (v2)
    range_config = models.JSONField(
        null=True,
        blank=True,
        help_text="Full RangeSpec from CMS (scenario_id, user_id, subnets)",
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
        # Keep using original table name from mission_control
        db_table = "mission_control_range"

    def __str__(self):
        scenario = self.range_config.get("scenario_id", "unknown") if self.range_config else "unknown"
        return f"Range {self.id} ({scenario}) - {self.status}"

    @property
    def is_usable(self):
        """Return True if range is in a usable state (operational and connectable)."""
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
    # Range VPC uses 10.1.0.0/16 with /28 subnets (16 IPs each)
    # Capacity: 253 third octets (2-254) x 16 /28 blocks = 4048 subnets
    SUBNET_INDEX_MIN = 1
    SUBNET_INDEX_MAX = 4048

    @classmethod
    def allocate_subnet_index(cls) -> int:
        """
        Allocate the next available subnet index for a new range.

        Uses SELECT FOR UPDATE to prevent race conditions when multiple
        ranges are being created concurrently.

        Returns:
            int: The allocated subnet index (1-4048)

        Raises:
            ValueError: If no subnet indices are available (4048 active ranges)
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

    def get_instance_by_uuid(self, uuid: str) -> dict | None:
        """Get instance details by UUID.

        Args:
            uuid: Instance UUID (required, non-empty)

        Returns:
            Dictionary with instance details or None if not found

        Raises:
            ValueError: If uuid is None or empty string
        """
        if not uuid:
            raise ValueError("uuid is required")
        if not self.provisioned_instances:
            return None
        for instance in self.provisioned_instances:
            if instance.get("uuid") == uuid:
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


class Subnet(Instantiation):
    """Logical subnet for CyberScript DSL routing.

    Represents a logical network segment from the CyberScript DSL.
    NOT an AWS subnet - this is realized as NGFW routes when a range
    with NGFW is provisioned.

    Tracks lifecycle for:
    - Creating NGFW address objects and routes on provision
    - Removing NGFW routes on destroy
    - Cleanup on failures

    Attributes:
        name: Logical subnet name from DSL (e.g., 'dc_network', 'server_network').
        connected_to: List of subnet names this subnet can reach (for NGFW routes).
        range: The Range this subnet belongs to.
    """

    name = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Logical subnet name from CyberScript DSL",
    )
    connected_to = models.JSONField(
        default=list,
        help_text="List of subnet names this subnet connects to (for NGFW routes)",
    )
    range = models.ForeignKey(
        Range,
        on_delete=models.CASCADE,
        related_name="logical_subnets",
        null=True,
        blank=True,
        help_text="Range this logical subnet belongs to",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Logical Subnet"
        verbose_name_plural = "Logical Subnets"

    def __str__(self):
        return f"Subnet {self.name} ({self.uuid})"

    @property
    def instance_uuids(self) -> list[str]:
        """Return list of instance UUIDs in this subnet.

        Extracts from spec if available, otherwise empty list.
        """
        if not self.spec:
            return []
        instances = self.spec.get("instances", [])
        return [inst.get("uuid") for inst in instances if inst.get("uuid")]


class SubnetAllocation(models.Model):
    """Tracks CIDR reservations to prevent race conditions during concurrent provisioning.

    When multiple ranges provision concurrently, there's a TOCTOU gap between
    selecting a free CIDR and Terraform actually creating the AWS subnet (~30-90s).
    This table reserves CIDRs at advisory-lock time so subsequent allocations
    see them as taken.

    Lifecycle:
        reserved → active (on successful Terraform apply)
        reserved → released (on provision failure)
        active → released (on range destroy)

    Stale reservations (>30min in 'reserved' status) are ignored during
    allocation, allowing reclamation if a provisioner crashes.
    """

    class Status(models.TextChoices):
        RESERVED = "reserved"
        ACTIVE = "active"
        RELEASED = "released"

    vpc_id = models.CharField(max_length=30)
    cidr = models.CharField(max_length=20, help_text="e.g. 10.1.2.16/28")
    subnet_size = models.IntegerField(help_text="Prefix length: 24 or 28")
    range_id = models.IntegerField()
    request_id = models.CharField(max_length=64)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RESERVED)
    reserved_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "engine_subnetallocation"
        indexes = [
            models.Index(fields=["vpc_id", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["vpc_id", "cidr"],
                condition=models.Q(status__in=["reserved", "active"]),
                name="unique_active_cidr_per_vpc",
            ),
        ]

    def __str__(self):
        return f"{self.cidr} in {self.vpc_id} ({self.status})"
