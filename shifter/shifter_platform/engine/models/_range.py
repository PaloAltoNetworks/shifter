"""Range model - user's cyber range instance with lifecycle management."""

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db import models

from shared.schemas.persistence import unwrap_persisted_spec

from ._range_allocation import RangeAllocationMixin
from ._range_egress import RANGE_EGRESS_DEFAULT, RANGE_EGRESS_MODE_CHOICES
from ._request import Request

if TYPE_CHECKING:
    from django.contrib.auth.models import User


class Range(RangeAllocationMixin, models.Model):
    """User's cyber range instance with lifecycle management."""

    class Status(models.TextChoices):
        """Lifecycle states a Range can occupy from creation through teardown."""

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
    # Soft reference to workspaces.Workspace (ADR-046-R3, #1325): a scalar, not a
    # cross-layer FK (ADR-001-R2) from the trusted CMS launch path; non-null, no default.
    workspace_id = models.IntegerField(
        null=True, blank=True, db_index=True, help_text="Workspace scope (soft reference; ADR-046/ADR-066)."
    )
    scope_kind = models.CharField(
        max_length=16, blank=True, default="", choices=(("installation", "Installation"), ("account", "Account"))
    )
    account_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    organization_id = models.PositiveBigIntegerField(null=True, blank=True)
    # Effective egress posture pinned at create under the workspace mutex, replay-verified (PLAT-238).
    egress_mode = models.CharField(
        max_length=16,
        choices=RANGE_EGRESS_MODE_CHOICES,
        default=RANGE_EGRESS_DEFAULT,
        help_text="Effective range egress posture pinned at create (PLAT-238; ADR-017-R5/ADR-026).",
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
    provisioner_operation = models.CharField(max_length=32, blank=True, default="")
    provisioner_operation_id = models.UUIDField(null=True, blank=True, editable=False)
    model_source_policy_revision = models.PositiveIntegerField(default=0)
    # Stable cloud ownership epoch; destroy has a different operation fence.
    resource_generation = models.UUIDField(null=True, blank=True, editable=False)
    # Range-backend ownership binding (#1666): write-once (backend, purpose) set at
    # create from the CMS BackendAdmission and validated via
    # shared.range_instantiation_policy; never re-derived from the GCP_RANGE_BACKEND
    # selector, so destroy/reconcile route from these facts and a gdc->gce flip
    # cannot strand ranges (ADR-030 / ADR-039). NULL (null=True intentional; DJ001 /
    # Sonar S6552 suppressed) is the load-bearing "no persisted binding" sentinel
    # for legacy pre-#1666 / non-GCP rows, distinct from any real backend value.
    range_backend = models.CharField(  # noqa: DJ001
        max_length=8,
        null=True,  # NOSONAR
        blank=True,
        help_text="Admitted GCP range backend bound at provision (#1666); NULL for legacy/non-GCP",
    )
    instantiation_purpose = models.CharField(  # noqa: DJ001
        max_length=24,
        null=True,  # NOSONAR
        blank=True,
        help_text="Trusted instantiation purpose bound at provision (#1666); NULL for legacy/non-GCP",
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
    placement_zone = models.CharField(max_length=63, blank=True, default="", help_text="GCE placement zone (#2029)")
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

    # Step Functions tracking (legacy — prefer provisioning_task_arn / teardown_task_arn)
    step_function_execution_arn = models.CharField(
        max_length=500, blank=True, default="", help_text="Legacy ECS task ARN (deprecated)"
    )
    provisioning_task_arn = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="ECS/GCP task identifier for the provisioning operation",
    )
    teardown_task_arn = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="ECS/GCP task identifier for the teardown operation",
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
    vpn_access_binding = models.JSONField(
        null=True,
        blank=True,
        help_text="Non-secret generation-bound OpenVPN access binding; profile material stays in provider secrets",
    )
    remote_access_capability = models.JSONField(
        null=True,
        blank=True,
        help_text="Server-issued non-secret authorization for optional range remote access",
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
        """Default ordering and legacy table name for the Range model."""

        ordering = ["-created_at"]
        # Keep using original table name from mission_control
        db_table = "mission_control_range"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        scope_kind="", account_id__isnull=True, organization_id__isnull=True, workspace_id__isnull=False
                    )
                    | models.Q(
                        scope_kind="installation",
                        account_id__isnull=True,
                        organization_id__isnull=True,
                        workspace_id__isnull=True,
                    )
                    | (
                        models.Q(scope_kind="account", account_id__isnull=False)
                        & (models.Q(workspace_id__isnull=True) | models.Q(organization_id__isnull=False))
                    )
                ),
                name="engine_range_resource_scope_shape",
            ),
        ]

    def __str__(self) -> str:
        """Return a human-readable label with id, scenario, and status."""
        config = unwrap_persisted_spec(self.range_config) if self.range_config else {}
        scenario = config.get("scenario_id", "unknown")
        return f"Range {self.id} ({scenario}) - {self.status}"

    @property
    def is_usable(self) -> bool:
        """Return True if range is in a usable state (operational and connectable).

        Delegates to ``engine._range_state.is_range_usable`` (#685); the
        status vocabulary is canonical ``shared.enums.ResourceStatus``. That
        module is dependency-neutral (no import of ``engine.models`` or
        ``engine.services``), so this stays a downward-only dependency even
        though ``engine.services._lifecycle`` re-exports the same function.
        """
        from engine._range_state import is_range_usable

        return is_range_usable(self.status)

    @property
    def is_terminal(self) -> bool:
        """Return True if range has reached a final state.

        Delegates to ``engine._range_state.is_range_terminal`` (#685); see
        ``is_usable`` for why the model imports the neutral module directly
        rather than ``engine.services._lifecycle``.
        """
        from engine._range_state import is_range_terminal

        return is_range_terminal(self.status)

    @property
    def standup_duration(self) -> timedelta | None:
        """Total time from creation to ready.

        Returns:
            timedelta if both created_at and ready_at are set, None otherwise
        """
        if self.ready_at and self.created_at:
            return self.ready_at - self.created_at
        return None

    @classmethod
    def get_active_for_user(cls, user: "User") -> "Range | None":
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
    def get_destroyable_for_user(cls, user: "User") -> "Range | None":
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

    @classmethod
    def resolve_active_for_instance(cls, user: "User", instance_uuid: str) -> "Range | None":
        """Return the user's active range that contains instance_uuid, or None.

        Iterates the user's active ranges (same status set as get_active_for_user)
        and returns the first one whose get_instance_by_uuid(instance_uuid) is
        non-None. Pure-Python iteration avoids provider-specific JSON DB lookups
        (e.g. ``provisioned_instances__contains``) that are not portable across
        SQLite and Postgres. Returns None if no active range contains the UUID.

        Used by terminal helpers (get_rdp_connection_info, get_ssh_connection_info)
        to resolve the correct range when a user holds multiple simultaneous
        active ranges (e.g. one Mission Control + one CTF range, #450).

        Args:
            user: The user whose active ranges to search.
            instance_uuid: The instance UUID to look up.

        Returns:
            Range if found, None otherwise.
        """
        active_ranges = cls.objects.filter(
            user=user,
            status__in=[
                cls.Status.PENDING,
                cls.Status.PROVISIONING,
                cls.Status.READY,
                cls.Status.PAUSED,
                cls.Status.RESUMING,
            ],
        )
        for range_obj in active_ranges:
            if range_obj.get_instance_by_uuid(instance_uuid) is not None:
                return range_obj
        return None

    # The ``provisioned_instances`` traversal below delegates to the pure,
    # dependency-neutral projection helpers in ``engine._range_state`` (#685).
    # ``engine.services._common`` re-exports the same functions for its own
    # callers; the model imports the neutral module directly rather than that
    # private service submodule so it does not depend upward on the service
    # layer (which already depends on the model). These thin methods remain as
    # a compatibility surface for existing callers/tests.

    def get_instance_by_role(self, role: str) -> dict | None:
        """Get instance details by role.

        Args:
            role: Instance role ("attacker" or "victim")

        Returns:
            Dictionary with instance details or None if not found
        """
        from engine._range_state import find_instance_by_role

        return find_instance_by_role(self.provisioned_instances, role)

    def get_instance_by_uuid(self, uuid: str) -> dict | None:
        """Get instance details by UUID.

        Args:
            uuid: Instance UUID (required, non-empty)

        Returns:
            Dictionary with instance details or None if not found

        Raises:
            ValueError: If uuid is None or empty string
        """
        from engine._range_state import find_instance_by_uuid

        return find_instance_by_uuid(self.provisioned_instances, uuid)

    @property
    def attacker_instance(self) -> dict | None:
        """Get the attacker instance details."""
        from engine._range_state import attacker_instance

        return attacker_instance(self.provisioned_instances)

    @property
    def victim_instances(self) -> list[dict[str, Any]]:
        """Get all victim instance details."""
        from engine._range_state import victim_instances

        return victim_instances(self.provisioned_instances)

    @property
    def kali_private_ip(self) -> str | None:
        """Get the Kali (attacker) instance private IP address.

        Returns:
            The private IP address string or None if not available
        """
        from engine._range_state import attacker_private_ip

        return attacker_private_ip(self.provisioned_instances)

    @property
    def victim_private_ip(self) -> str | None:
        """Get the first victim instance private IP address.

        Returns:
            The private IP address string or None if not available
        """
        from engine._range_state import first_victim_private_ip

        return first_victim_private_ip(self.provisioned_instances)
