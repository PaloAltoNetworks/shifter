"""Engine-owned immutable model allocations and exact-integer capacity ledger.

Model metrics extend ADR-047's assessment/draw boundary without changing the
advisory compute ledger's floating units. All original references survive
revocation and deletion of upstream domain objects.
"""

from uuid import uuid4

from django.db import models


class ModelQuotaIdentity(models.Model):
    """Durable mutex for a real quota, including across catalog renames."""

    identity = models.CharField(max_length=71, primary_key=True)
    deployment_id = models.UUIDField(db_index=True)
    provider_adapter_id = models.CharField(max_length=128)
    provider_quota_identity = models.CharField(max_length=256)
    dimension = models.CharField(max_length=128)
    unit = models.CharField(max_length=64)

    class Meta:
        """Enforce one durable identity for each physical provider quota."""

        constraints = [
            models.UniqueConstraint(
                fields=["deployment_id", "provider_adapter_id", "provider_quota_identity", "dimension", "unit"],
                name="model_quota_real_identity",
            )
        ]

    def __str__(self) -> str:
        return str(self.pk)


class ModelAllocation(models.Model):
    """Complete admitted map bound to the incumbent launch operation generation."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    deployment_id = models.UUIDField()
    request_id = models.UUIDField(db_index=True)
    operation_id = models.UUIDField(db_index=True)
    range_id = models.UUIDField(db_index=True)
    draw_key = models.UUIDField(db_index=True)
    workload_role = models.CharField(max_length=128)
    source_policy_revision = models.PositiveIntegerField(default=0)
    intent_digest = models.CharField(max_length=71)
    policy_digest = models.CharField(max_length=71)
    alias_shards = models.JSONField()
    snapshot = models.JSONField()
    deadline = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    released_at = models.DateTimeField(null=True)
    # M04 must hold this fence while adding request liabilities; a lifecycle
    # event alone cannot prove a provider request stopped.
    unresolved_liabilities = models.PositiveBigIntegerField(default=0)

    class Meta:
        """Prevent duplicate admissions for a launch operation and workload."""

        constraints = [
            models.UniqueConstraint(
                fields=["request_id", "operation_id", "workload_role", "source_policy_revision"],
                name="model_allocation_operation_role",
            )
        ]

    def __str__(self) -> str:
        return str(self.pk)


class ModelPendingGrant(models.Model):
    """Non-usable enrollment binding; M03 neither issues nor stores credentials."""

    public_id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    allocation = models.OneToOneField(ModelAllocation, on_delete=models.PROTECT, related_name="grant")
    grant_epoch = models.PositiveBigIntegerField(default=1)
    state = models.CharField(max_length=16, default="pending")
    revoked_at = models.DateTimeField(null=True)

    class Meta:
        """Constrain the pending-grant epoch and closed state vocabulary."""

        constraints = [
            models.CheckConstraint(condition=models.Q(grant_epoch__gt=0), name="model_grant_positive_epoch"),
            models.CheckConstraint(
                condition=models.Q(state__in=["pending", "active", "revoked"]), name="model_grant_closed_state"
            ),
        ]

    def __str__(self) -> str:
        return str(self.pk)


class ModelAllocationAuthority(models.Model):
    """Pinned expected revision of existing authority, never a second authority."""

    allocation = models.ForeignKey(ModelAllocation, on_delete=models.PROTECT, related_name="authorities")
    fence = models.ForeignKey("engine.SharingAuthorityFence", on_delete=models.PROTECT)
    revision = models.PositiveBigIntegerField()

    class Meta:
        """Pin one revision of each authority fence per allocation."""

        constraints = [models.UniqueConstraint(fields=["allocation", "fence"], name="model_allocation_fence_once")]

    def __str__(self) -> str:
        return str(self.pk)


class ModelCapacityReservation(models.Model):
    """One parent commitment per logical capacity scope, real quota and window."""

    quota = models.ForeignKey(ModelQuotaIdentity, on_delete=models.PROTECT, related_name="reservations")
    assessment = models.ForeignKey("engine.CapacityAssessment", on_delete=models.PROTECT)
    scope_key = models.CharField(max_length=256)
    window_start = models.DateTimeField()
    window_end = models.DateTimeField()
    amount = models.PositiveBigIntegerField()
    consumed = models.PositiveBigIntegerField(default=0)
    released_at = models.DateTimeField(null=True)
    observation = models.JSONField()
    workload_budgets = models.JSONField(default=dict)

    class Meta:
        """Constrain capacity commitments and their overlap lookup."""

        constraints = [
            models.UniqueConstraint(
                fields=["quota", "scope_key", "window_start", "window_end"], name="model_capacity_scope_window"
            ),
            models.CheckConstraint(
                condition=models.Q(consumed__lte=models.F("amount")), name="model_capacity_draw_ceiling"
            ),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="model_capacity_positive"),
            models.CheckConstraint(
                condition=models.Q(window_end__gt=models.F("window_start")), name="model_capacity_window"
            ),
        ]
        indexes = [
            models.Index(fields=["quota", "released_at", "window_start", "window_end"], name="model_quota_overlap")
        ]

    def __str__(self) -> str:
        return str(self.pk)


class ModelCapacityDraw(models.Model):
    """Exact generation-bound child; never counted as another provider commitment."""

    allocation = models.ForeignKey(ModelAllocation, on_delete=models.PROTECT, related_name="draws")
    reservation = models.ForeignKey(ModelCapacityReservation, on_delete=models.PROTECT, related_name="draws")
    amount = models.PositiveBigIntegerField()
    released_at = models.DateTimeField(null=True)

    class Meta:
        """Record one positive draw per allocation and reservation."""

        constraints = [
            models.UniqueConstraint(fields=["allocation", "reservation"], name="model_draw_allocation_once"),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="model_draw_positive"),
        ]

    def __str__(self) -> str:
        return str(self.pk)


class ModelAliasAssignment(models.Model):
    """Pinned first-use choice for one shared group and alias."""

    group = models.ForeignKey("engine.AllocationGroup", on_delete=models.PROTECT, related_name="assignments")
    logical_alias = models.CharField(max_length=128)
    shard = models.JSONField()
    policy_digest = models.CharField(max_length=71)

    class Meta:
        """Pin one shard assignment for each shared group alias."""

        constraints = [models.UniqueConstraint(fields=["group", "logical_alias"], name="model_group_alias_once")]

    def __str__(self) -> str:
        return str(self.pk)


class ModelLaunchPreparationRecord(models.Model):
    """Trusted CMS input waiting to bind the incumbent launch generation."""

    request_id = models.UUIDField(primary_key=True)
    intent_digest = models.CharField(max_length=71)
    intent = models.JSONField()
    catalog = models.JSONField(null=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return str(self.pk)


class ModelQuotaReading(models.Model):
    """Latest pre-transaction reading bound to an exact catalog revision."""

    catalog_digest = models.CharField(max_length=71)
    quota_pool_id = models.CharField(max_length=128)
    observed_at = models.DateTimeField()
    observation = models.JSONField()

    class Meta:
        """Keep one latest reading per catalog revision and quota pool."""

        constraints = [
            models.UniqueConstraint(fields=["catalog_digest", "quota_pool_id"], name="model_quota_reading_revision")
        ]

    def __str__(self) -> str:
        return str(self.pk)


class ModelOptionalAbsence(models.Model):
    """A replay-stable optional workload decision; never a grant or reservation."""

    request_id = models.UUIDField()
    operation_id = models.UUIDField()
    workload_role = models.CharField(max_length=128)
    source_policy_revision = models.PositiveIntegerField(default=0)
    intent_digest = models.CharField(max_length=71)
    reason = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Keep one optional-absence decision per operation workload."""

        constraints = [
            models.UniqueConstraint(
                fields=["request_id", "operation_id", "workload_role", "source_policy_revision"],
                name="model_optional_operation_role",
            )
        ]

    def __str__(self) -> str:
        return str(self.pk)
