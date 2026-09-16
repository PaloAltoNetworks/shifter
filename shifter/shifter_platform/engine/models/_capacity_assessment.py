"""Capacity assessment and reservation models (PLAT-201, #680).

:class:`CapacityDeclaration` records *intent* -- how big an event expects to be.
These two record what the Engine did with that intent:

``CapacityAssessment`` is an immutable snapshot of one admission decision,
pinned to the partition, the policy version, and the time the underlying
readings were taken. It is append-only history: a re-assessment writes a new row
rather than mutating the old one, so a later retry, destroy, or reconciliation
reads the decision that was actually made rather than re-deriving it against
configuration that has since drifted.

``CapacityReservation`` is the durable commitment that makes overlapping events
account for each other. Provider quotas cannot be reserved server-side, so this
table is the only place Shifter knows that another event has already promised to
consume capacity in the same partition during an overlapping window.
"""

from __future__ import annotations

from django.db import models


class CapacityAssessment(models.Model):
    """One immutable capacity-admission decision for one event."""

    event_ref = models.UUIDField(
        db_index=True,
        help_text="Upstream event identifier (opaque to the engine; no FK by design)",
    )
    partition_name = models.CharField(
        max_length=100,
        help_text="Deployment-declared target partition this decision was made against",
    )
    policy_version = models.CharField(
        max_length=64,
        help_text="Fingerprint of the capacity catalog that produced the decision",
    )
    outcome = models.CharField(
        max_length=20,
        help_text="admitted | warning | indeterminate | rejected",
    )
    verdicts = models.JSONField(
        default=list,
        blank=True,
        help_text="Per-metric bounded reason codes; never raw provider limits or usage figures",
    )
    observed_at = models.DateTimeField(
        help_text="When the underlying provider readings were taken (not when we asked)",
    )
    assessed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Table metadata."""

        db_table = "engine_capacity_assessment"
        ordering = ["-assessed_at"]
        indexes = [
            models.Index(fields=["event_ref", "-assessed_at"]),
            models.Index(fields=["partition_name", "-assessed_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.event_ref}@{self.partition_name} -> {self.outcome} ({self.assessed_at})"


class CapacityReservation(models.Model):
    """Capacity one event has committed to consume in a partition and window.

    Open rows (``released_at`` null) whose window overlaps a candidate event's
    window are subtracted from observed headroom, so two events planned into the
    same account cannot each be told the whole quota is free.
    """

    assessment = models.ForeignKey(
        CapacityAssessment,
        on_delete=models.CASCADE,
        related_name="reservations",
        null=True,
        blank=True,
        help_text="Assessment that created this reservation",
    )
    event_ref = models.UUIDField(
        db_index=True,
        help_text="Upstream event identifier holding the reservation",
    )
    request_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Provisioning request correlation id, when the reservation is request-scoped",
    )
    partition_name = models.CharField(max_length=100, help_text="Partition the capacity is held in")
    metric_name = models.CharField(max_length=100, help_text="Catalog metric the capacity is held against")
    amount = models.FloatField(help_text="Total amount of the metric's unit committed for the whole event")
    consumed = models.FloatField(
        default=0.0,
        help_text="Amount of the committed budget drawn down by admitted ranges",
    )
    unit_amount = models.FloatField(
        default=0.0,
        help_text="Amount one range draws from this budget when admitted",
    )
    enforcement = models.CharField(
        max_length=16,
        default="advisory",
        help_text="Enforcement mode in force when the budget was sized (advisory | enforcing)",
    )
    window_start = models.DateTimeField(help_text="Start of the window this reservation occupies")
    window_end = models.DateTimeField(help_text="End of the window this reservation occupies")
    released_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set when the reservation is released; released rows no longer consume headroom",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Table metadata."""

        db_table = "engine_capacity_reservation"
        ordering = ["-created_at"]
        indexes = [
            # The overlap query filters on exactly this shape.
            models.Index(fields=["partition_name", "metric_name", "released_at"]),
            models.Index(fields=["event_ref", "released_at"]),
        ]
        constraints = [
            # The race-proof backstop. The read-then-write check in the admit
            # service is the friendly path; concurrent draws are stopped here,
            # mirroring the active-range partial-unique precedent (#307).
            models.CheckConstraint(
                condition=models.Q(consumed__lte=models.F("amount")),
                name="capacity_reservation_consumed_within_budget",
            ),
            models.CheckConstraint(
                condition=models.Q(consumed__gte=0),
                name="capacity_reservation_consumed_non_negative",
            ),
        ]

    def __str__(self) -> str:
        state = "released" if self.released_at else "open"
        return f"{self.metric_name}={self.consumed}/{self.amount} @ {self.partition_name} ({state})"

    @property
    def available(self) -> float:
        """Budget still undrawn."""
        return self.amount - self.consumed


class CapacityDraw(models.Model):
    """One range's draw against an event capacity budget.

    Exists so admission is idempotent and reversible per provisioning request:
    a retried create must not draw twice, and a destroyed range must return its
    share. Without this ledger a budget could only ever be released wholesale,
    which is what makes long-running events leak capacity.
    """

    reservation = models.ForeignKey(
        CapacityReservation,
        on_delete=models.CASCADE,
        related_name="draws",
        help_text="Budget this draw is taken from",
    )
    event_ref = models.UUIDField(db_index=True, help_text="Event the drawing range belongs to")
    draw_key = models.UUIDField(
        db_index=True,
        help_text=(
            "Stable identity of the thing drawing (participant, spare, or replacement). "
            "Known before the range exists, so admission can decide before creation and "
            "a retry of the same creation cannot draw twice."
        ),
    )
    request_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Provisioning request id, attached after creation for correlation",
    )
    amount = models.FloatField(help_text="Amount drawn from the budget")
    created_at = models.DateTimeField(auto_now_add=True)
    released_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set when the draw is returned to its budget",
    )

    class Meta:
        """Table metadata."""

        db_table = "engine_capacity_draw"
        ordering = ["-created_at"]
        constraints = [
            # One open draw per (request, budget): the idempotence guarantee
            # that survives a concurrent retry, not just a sequential one.
            models.UniqueConstraint(
                fields=["reservation", "draw_key"],
                condition=models.Q(released_at__isnull=True),
                name="capacity_draw_one_open_per_key",
            ),
        ]
        indexes = [
            models.Index(fields=["draw_key", "released_at"]),
        ]

    def __str__(self) -> str:
        state = "released" if self.released_at else "open"
        return f"draw {self.amount} for {self.draw_key} ({state})"
