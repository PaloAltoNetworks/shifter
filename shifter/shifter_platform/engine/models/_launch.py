"""ProvisionerLaunchStatus enum and ProvisionerLaunchIntent model."""

import uuid

from django.db import models


class ProvisionerLaunchStatus(models.TextChoices):
    """Lifecycle values for a durable provisioner launch request."""

    PENDING = "PENDING", "Pending"
    RUNNING = "RUNNING", "Running"
    SUCCEEDED = "SUCCEEDED", "Succeeded"
    DLQ = "DLQ", "Dead Letter Queue"


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
