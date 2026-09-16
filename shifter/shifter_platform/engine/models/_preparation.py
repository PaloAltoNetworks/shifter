"""Deployment-local adapter administration, separate from range lifecycle state."""

from uuid import uuid4

from django.conf import settings
from django.db import models


class PreparationScopeLock(models.Model):
    """Serialize capacity admission across grant versions in one backend scope.

    This row is a mutex, not a tenant identity or a capacity counter. Capacity is
    derived from durable operations while holding its database row lock.
    """

    scope_digest = models.CharField(max_length=71, primary_key=True)

    def __str__(self) -> str:
        return f"Preparation scope {self.scope_digest}"


class PreparationGrant(models.Model):
    """Immutable operator grant for an already provisioned worker security profile.

    The cloud-operator installation path verifies and records this grant. Pack
    authors and adapter installers cannot create IAM/RBAC grants by declaring
    requirements. Revocation changes ``active``; it never rewrites the pinned
    configuration used by existing operations and independent cleanup.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    scope_digest = models.CharField(max_length=71, db_index=True)
    configuration_digest = models.CharField(max_length=71, unique=True)
    configuration = models.JSONField()
    active = models.BooleanField(default=False)
    installation_digest = models.CharField(max_length=71, blank=True)
    installation = models.JSONField(default=dict)
    verified_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Cloud authority is distinct from application adapter administration."""

        permissions = [("manage_preparation_grants", "Manage artifact preparation cloud grants")]

    def __str__(self) -> str:
        return f"Preparation grant {self.id}"


class PreparationAdapter(models.Model):
    """One immutable executable registration; upgrades create another version."""

    class State(models.TextChoices):
        """Lifecycle controls new preparation, without deleting pinned history."""

        ENABLED = "enabled", "Enabled"
        DISABLED = "disabled", "Disabled"
        RETIRED = "retired", "Retired"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    grant = models.ForeignKey(PreparationGrant, on_delete=models.PROTECT)
    scope_digest = models.CharField(max_length=71)
    adapter_id = models.CharField(max_length=128)
    version = models.CharField(max_length=128)
    manifest_digest = models.CharField(max_length=71)
    manifest = models.JSONField()
    state = models.CharField(max_length=16, choices=State.choices, default=State.ENABLED)
    installed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Database uniqueness is the concurrent-install identity fence."""

        permissions = [
            ("manage_preparation_adapters", "Install and administer artifact preparation adapters"),
            ("prepare_artifacts", "Request and inspect artifact preparation"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["scope_digest", "adapter_id", "version"], name="prep_adapter_identity"),
            models.CheckConstraint(
                condition=models.Q(state__in=["enabled", "disabled", "retired"]), name="prep_adapter_state"
            ),
        ]

    def __str__(self) -> str:
        return f"Preparation adapter {self.id} ({self.state})"


class PreparationOperation(models.Model):
    """Authoritative preparation lifecycle; the range provisioner never reads it."""

    class State(models.TextChoices):
        """Available requires independent verification and atomic inventory admission."""

        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        VERIFYING = "verifying", "Verifying"
        AVAILABLE = "available", "Available"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    adapter = models.ForeignKey(PreparationAdapter, on_delete=models.PROTECT)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    scope_digest = models.CharField(max_length=71, db_index=True)
    input_digest = models.CharField(max_length=71, unique=True)
    input = models.JSONField()
    state = models.CharField(max_length=16, choices=State.choices, default=State.QUEUED, db_index=True)
    current_attempt_id = models.UUIDField(null=True, editable=False)
    cleanup_pending = models.BooleanField(default=False, db_index=True)
    failure_code = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """A durable unique input is the request idempotency boundary."""

        constraints = [
            models.CheckConstraint(
                condition=models.Q(state__in=["queued", "running", "verifying", "available", "failed", "cancelled"]),
                name="prep_operation_state",
            ),
        ]

    def __str__(self) -> str:
        return f"Artifact preparation {self.id} ({self.state})"


class PreparationAttempt(models.Model):
    """Immutable input and result inbox for one separately authenticated worker.

    Dispatch uses this UUID as its deterministic Job identity. Results bind its
    immutable digest; changing operation generation fences every earlier worker.
    Only the controller can commit domain state or inventory.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    operation = models.ForeignKey(PreparationOperation, on_delete=models.PROTECT)
    phase = models.CharField(max_length=16)
    input = models.JSONField()
    input_digest = models.CharField(max_length=71)
    expires_at = models.DateTimeField()
    dispatched_at = models.DateTimeField(null=True)
    next_dispatch_at = models.DateTimeField()
    dispatch_count = models.PositiveIntegerField(default=0)
    lease_id = models.UUIDField(null=True)
    lease_expires_at = models.DateTimeField(null=True)
    result = models.JSONField(null=True)
    result_digest = models.CharField(max_length=71, blank=True, default="")
    disposition = models.CharField(max_length=24, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Bound phase vocabulary; dispatch scans only indexed pending work."""

        constraints = [
            models.CheckConstraint(
                condition=models.Q(phase__in=["verify-inputs", "build", "verify-output", "cleanup"]),
                name="prep_attempt_phase",
            ),
        ]
        indexes = [models.Index(fields=["disposition", "next_dispatch_at"], name="prep_attempt_dispatch")]

    def __str__(self) -> str:
        return f"Preparation attempt {self.id} ({self.phase})"


class PreparedArtifactAdmission(models.Model):
    """Verified materialization facts committed atomically with ordinary inventory."""

    operation = models.OneToOneField(PreparationOperation, on_delete=models.PROTECT)
    image_mapping = models.OneToOneField("engine.RaesImageMapping", on_delete=models.PROTECT)
    scope_digest = models.CharField(max_length=71, db_index=True)
    facts = models.JSONField()
    facts_digest = models.CharField(max_length=71)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Prepared artifact {self.operation_id}"
