"""OutboxStatus enum and RangeEventOutbox model."""

from django.db import models


class OutboxStatus(models.TextChoices):
    """Valid lifecycle values for RangeEventOutbox.status."""

    PENDING = "PENDING", "Pending"
    PUBLISHED = "PUBLISHED", "Published"
    FAILED = "FAILED", "Failed"
    DLQ = "DLQ", "Dead Letter Queue"


class RangeEventOutbox(models.Model):
    """Transactional outbox for range events.

    The provisioner writes a row here inside the same DB transaction as the
    authoritative state change (e.g. update_range_status).  A separate drainer
    process reads PENDING rows, publishes them to the event bus, and marks them
    PUBLISHED.  Failures retry up to max_attempts before being moved to DLQ.

    Payload must be notification-shaped: IDs only, no secrets or instance state.
    last_error must be bounded/sanitised by the writer before storing.
    """

    id = models.BigAutoField(primary_key=True)
    event_id = models.UUIDField(unique=True, db_index=True)
    event_type = models.CharField(max_length=64)
    payload = models.JSONField()
    status = models.CharField(
        max_length=16,
        default=OutboxStatus.PENDING,
        db_index=True,
        choices=OutboxStatus.choices,
    )
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=10)
    next_attempt_at = models.DateTimeField(db_index=True)
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        """Table configuration for the range event outbox."""

        db_table = "engine_range_event_outbox"
        indexes = [
            models.Index(fields=["status", "next_attempt_at"], name="engine_rang_status_6f706a_idx"),
        ]

    def __str__(self) -> str:
        return f"RangeEventOutbox {self.event_id} ({self.status})"
