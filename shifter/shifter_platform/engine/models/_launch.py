"""ProvisionerLaunchStatus enum and ProvisionerLaunchIntent model."""

import uuid

from django.db import models


class ProvisionerLaunchStatus(models.TextChoices):
    """Lifecycle values for a durable provisioner launch request.

    This is *launch delivery* status only: ``SUCCEEDED`` means the provider task
    was dispatched, not that the task or its range operation succeeded, and
    ``DLQ`` is dispatch exhaustion -- never a synonym for user cancellation.
    Cancellation rides the separate ``InterruptState`` machine below (#277).
    """

    PENDING = "PENDING", "Pending"
    RUNNING = "RUNNING", "Running"
    SUCCEEDED = "SUCCEEDED", "Succeeded"
    DLQ = "DLQ", "Dead Letter Queue"


class InterruptState(models.TextChoices):
    """Disposition of a durable provision-task interrupt (#277).

    Kept distinct from ``ProvisionerLaunchStatus`` because interrupt delivery has
    its own bounded retry/deadline and convergence. ``NONE`` is the no-interrupt
    default; ``DESTROY_ENQUEUED`` and ``IDENTITY_MISMATCH`` are terminal (success
    and fail-closed respectively).
    """

    NONE = "", "None"
    REQUESTED = "REQUESTED", "Requested"
    SUPPRESSED = "SUPPRESSED", "Suppressed"
    STOPPING = "STOPPING", "Stopping"
    TERMINAL_ABSENT = "TERMINAL_ABSENT", "Terminal absent"
    DESTROY_ENQUEUED = "DESTROY_ENQUEUED", "Destroy enqueued"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH", "Identity mismatch"
    UNKNOWN = "UNKNOWN", "Unknown"
    # Terminal fail-closed: the bounded interrupt deadline elapsed without a
    # confirmed terminal absence. The range stays DESTROYING (never destroyed) and
    # an operator signal is emitted rather than churning the retry loop forever.
    EXHAUSTED = "EXHAUSTED", "Exhausted"


class ProvisionerLaunchIntent(models.Model):
    """Minimal, secret-free intent consumed only by the launcher worker."""

    intent_id = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    operation_id = models.UUIDField(editable=False, unique=True)
    idempotency_key = models.CharField(max_length=255)
    payload = models.JSONField()
    status = models.CharField(
        max_length=16,
        default=ProvisionerLaunchStatus.PENDING,
        choices=ProvisionerLaunchStatus.choices,
        db_index=True,
    )
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=10)
    next_attempt_at = models.DateTimeField(db_index=True)
    last_error = models.CharField(max_length=128, blank=True, default="")
    task_ref = models.CharField(max_length=512, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    launched_at = models.DateTimeField(null=True, blank=True)
    # Durable interrupt control (#277). Separate from launch delivery status: a
    # cancel records REQUESTED against the current provision generation; the
    # launcher worker converges it (suppress pending / stop running / observe
    # terminal absence / enqueue canonical destroy) with its own bounded retry.
    interrupt_state = models.CharField(
        max_length=24,
        default=InterruptState.NONE,
        choices=InterruptState.choices,
        blank=True,
        db_index=True,
    )
    interrupt_requested_at = models.DateTimeField(null=True, blank=True)
    interrupt_attempts = models.PositiveIntegerField(default=0)
    interrupt_next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    interrupt_deadline = models.DateTimeField(null=True, blank=True)
    interrupt_last_error = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        """Table configuration for durable provisioner launch intents."""

        db_table = "engine_provisioner_launch_intent"
        constraints = [
            models.UniqueConstraint(
                fields=["idempotency_key"],
                name="unique_provisioner_launch_operation",
            )
        ]
        indexes = [
            models.Index(fields=["status", "next_attempt_at"], name="engine_prov_status_due_idx"),
        ]

    def __str__(self) -> str:
        return f"ProvisionerLaunchIntent {self.intent_id} ({self.status})"
