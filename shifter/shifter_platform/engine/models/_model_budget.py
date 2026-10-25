"""Engine-owned request budgets, dispatch leases and reconciliation records (M04).

These records enforce integer-money spend, rate and concurrency budgets before a
possibly billable provider effect and hold a conservative charge when execution
is ambiguous. Each concept the accounting contract keeps separate has its own
table (ADR-060/061, request-accounting preflight #2121): a durable
account/window balance, a request reservation, one posting per applicable
account, dispatch/continuation lease state, and a reconciliation obligation.
The immutable account *definition* is contract data captured in the allocation
snapshot, not a mutable row here.

Money and token quantities are bounded non-negative integers; floating-point
capacity units are never reused for money. The mutable ``limit`` ceiling may be
reduced below already committed value, so no database constraint requires it to
stay above ``spent + reserved`` - admission enforces ``S + R + U <= B`` inside
the reserve transaction instead.
"""

from uuid import uuid4

from django.db import models

_DISPATCH_STATES = ["reserved", "dispatched", "settled", "unknown"]
_SETTLEMENT_STATES = ["open", "settled", "unknown_charged"]
_TRANSPORT_STATES = ["dispatching", "active", "revoking", "revoked", "closed"]
_POSTING_STATES = ["held", "settled", "released"]
_RECONCILIATION_OUTCOMES = ["unknown", "charged", "settled", "adjusted"]


class ModelBudgetAccount(models.Model):
    """One durable balance identity for an account within an explicit UTC window."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    deployment_id = models.UUIDField(db_index=True)
    account_ref = models.CharField(max_length=128)
    dimension = models.CharField(max_length=16)
    unit = models.CharField(max_length=64)
    currency = models.CharField(max_length=8, blank=True, default="")
    window_start = models.DateTimeField()
    window_end = models.DateTimeField()
    limit = models.PositiveBigIntegerField()
    spent = models.PositiveBigIntegerField(default=0)
    reserved = models.PositiveBigIntegerField(default=0)
    requests = models.PositiveBigIntegerField(default=0)
    active_leases = models.PositiveBigIntegerField(default=0)
    definition_revision = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Keep one balance per account and window; never cap committed value."""

        constraints = [
            models.UniqueConstraint(
                fields=["deployment_id", "account_ref", "window_start", "window_end"],
                name="model_budget_account_window",
            ),
            models.CheckConstraint(
                condition=models.Q(window_end__gt=models.F("window_start")),
                name="model_budget_account_window_order",
            ),
            models.CheckConstraint(
                condition=models.Q(dimension__in=["spend", "rate", "concurrency"]),
                name="model_budget_account_dimension",
            ),
        ]
        indexes = [models.Index(fields=["deployment_id", "account_ref"], name="model_budget_account_lookup")]

    def __str__(self) -> str:
        return str(self.pk)


class ModelRequestReservation(models.Model):
    """A request bound to its allocation, account set, prices, epoch and intent."""

    # Integer surrogate identity for safe audit correlation; the broker-generated
    # request UUID is a separate unique field (never a prompt-derived value).
    request_uuid = models.UUIDField(default=uuid4, unique=True, editable=False)
    allocation = models.ForeignKey(
        "engine.ModelAllocation", on_delete=models.PROTECT, related_name="request_reservations"
    )
    operation_id = models.UUIDField(db_index=True)
    grant_epoch = models.PositiveBigIntegerField()
    logical_alias = models.CharField(max_length=128)
    shard = models.JSONField()
    # An empty caller key means the request supplied no idempotency key and is a
    # new invocation; the scoped-uniqueness constraint below excludes the empty case.
    caller_key_hmac = models.CharField(max_length=71, blank=True, default="")
    key_version = models.CharField(max_length=32, blank=True, default="")
    intent_fingerprint_hmac = models.CharField(max_length=71, blank=True, default="")
    intent_contract_version = models.CharField(max_length=64, blank=True, default="")
    reservation_vector = models.JSONField()
    # The billing components the conservative bound covered; settlement must have
    # authoritative usage for every one of them before releasing the hold.
    billed_components = models.JSONField(default=list)
    canonical_request_cost = models.PositiveBigIntegerField()
    billing_bound = models.JSONField(default=dict)
    state = models.CharField(max_length=16, default="reserved")
    settlement_state = models.CharField(max_length=16, default="open")
    uncertainty_reason = models.CharField(max_length=64, blank=True, default="")
    provider_request_ref = models.CharField(max_length=256, blank=True, default="")
    usage = models.JSONField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Scope an optional retry key to the grant epoch and operation."""

        constraints = [
            models.UniqueConstraint(
                fields=["allocation", "grant_epoch", "operation_id", "caller_key_hmac"],
                condition=~models.Q(caller_key_hmac=""),
                name="model_request_retry_key",
            ),
            models.CheckConstraint(condition=models.Q(state__in=_DISPATCH_STATES), name="model_request_state"),
            models.CheckConstraint(
                condition=models.Q(settlement_state__in=_SETTLEMENT_STATES),
                name="model_request_settlement_state",
            ),
        ]
        indexes = [models.Index(fields=["state", "settlement_state"], name="model_request_state_scan")]

    def __str__(self) -> str:
        return str(self.pk)


class ModelBudgetPosting(models.Model):
    """One hold/charge for a distinct applicable account, locked and posted once."""

    reservation = models.ForeignKey(ModelRequestReservation, on_delete=models.PROTECT, related_name="postings")
    account = models.ForeignKey(ModelBudgetAccount, on_delete=models.PROTECT, related_name="postings")
    held = models.PositiveBigIntegerField()
    settled = models.PositiveBigIntegerField(default=0)
    state = models.CharField(max_length=16, default="held")
    # The account-definition revision pinned at reservation, so settlement and
    # audit reference the semantics that authorized the hold, not a later mutation.
    definition_revision = models.PositiveBigIntegerField(default=0)

    class Meta:
        """Record exactly one posting per request and account/window."""

        constraints = [
            models.UniqueConstraint(fields=["reservation", "account"], name="model_budget_posting_once"),
            models.CheckConstraint(condition=models.Q(state__in=_POSTING_STATES), name="model_budget_posting_state"),
        ]

    def __str__(self) -> str:
        return str(self.pk)


class ModelDispatchLease(models.Model):
    """The single dispatch attempt and continuation fence for one request."""

    reservation = models.OneToOneField(ModelRequestReservation, on_delete=models.PROTECT, related_name="lease")
    dispatch_token = models.CharField(max_length=64)
    dispatch_deadline = models.DateTimeField()
    continuation_revision = models.PositiveBigIntegerField(default=0)
    continuation_deadline = models.DateTimeField(null=True)
    transport_status = models.CharField(max_length=16, default="dispatching")
    acknowledged = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Constrain the transport fence vocabulary; one lease per request."""

        constraints = [
            models.CheckConstraint(
                condition=models.Q(transport_status__in=_TRANSPORT_STATES), name="model_lease_transport_status"
            )
        ]

    def __str__(self) -> str:
        return str(self.pk)


class ModelReconciliationObligation(models.Model):
    """A durable obligation for an unresolved dispatch outcome; never auto-refunds."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    reservation = models.OneToOneField(ModelRequestReservation, on_delete=models.PROTECT, related_name="reconciliation")
    allocation = models.ForeignKey(
        "engine.ModelAllocation", on_delete=models.PROTECT, related_name="reconciliation_obligations"
    )
    provider_request_ref = models.CharField(max_length=256, blank=True, default="")
    next_attempt_at = models.DateTimeField()
    outcome = models.CharField(max_length=16, default="unknown")
    last_observation = models.JSONField(null=True)
    attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Constrain the reconciliation outcome vocabulary and scan order."""

        constraints = [
            models.CheckConstraint(
                condition=models.Q(outcome__in=_RECONCILIATION_OUTCOMES), name="model_reconciliation_outcome"
            )
        ]
        indexes = [models.Index(fields=["outcome", "next_attempt_at"], name="model_reconciliation_scan")]

    def __str__(self) -> str:
        return str(self.pk)
