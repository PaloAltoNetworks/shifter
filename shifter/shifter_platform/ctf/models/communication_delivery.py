"""Delivery command and inbox models for scoped CTF communications."""

from __future__ import annotations

from django.db import models

from ctf.enums_communication import CommunicationChannel, DeliveryStatus

from ._base import CTFBaseModel
from .communication import _REF_MAX, CommunicationIntent, RecipientSnapshot


class DeliveryAttempt(CTFBaseModel):
    """One durable per-transport delivery command for one recipient snapshot."""

    intent = models.ForeignKey(CommunicationIntent, on_delete=models.CASCADE, related_name="delivery_attempts")
    snapshot = models.ForeignKey(RecipientSnapshot, on_delete=models.CASCADE, related_name="delivery_attempts")
    channel = models.CharField(max_length=16, choices=CommunicationChannel.choices())
    status = models.CharField(
        max_length=24,
        choices=DeliveryStatus.choices(),
        default=DeliveryStatus.QUEUED.value,
        help_text="queued | claimed | retry_due | accepted | permanent_failure | cancelled | suppressed | expired",
    )
    attempt_number = models.PositiveIntegerField(default=0, help_text="Incremented per transport retry")
    idempotency_key = models.CharField(max_length=_REF_MAX, help_text="Stable per (intent, snapshot, channel)")
    due_at = models.DateTimeField(null=True, blank=True, help_text="When the command is next due to be claimed")
    result_reason = models.CharField(max_length=64, blank=True, default="", help_text="Bounded terminal reason class")
    provider_receipt = models.CharField(
        max_length=_REF_MAX,
        blank=True,
        default="",
        help_text="Optional stable backend message identity for at-least-once de-duplication; never provider text",
    )
    lease_token = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Opaque per-claim fence; a stale worker whose token no longer matches cannot record an outcome",
    )
    lease_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When a CLAIMED lease may be reclaimed by another worker (stale-lease recovery)",
    )
    first_attempt_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="First transport-attempt time; the stable baseline for the elapsed-time ceiling across retries",
    )
    attempted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Latest transport-attempt boundary: set just before the call, never proof of acceptance",
    )
    observed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the worker persisted the observed transport outcome",
    )

    class Meta:
        """Django model metadata and delivery-command constraints."""

        db_table = "ctf_communication_delivery_attempt"
        verbose_name = "CTF Delivery Attempt"
        verbose_name_plural = "CTF Delivery Attempts"
        constraints = [
            models.UniqueConstraint(fields=["snapshot", "channel"], name="ctf_comm_unique_snapshot_channel"),
            models.CheckConstraint(
                condition=models.Q(status__in=[s.value for s in DeliveryStatus]),
                name="ctf_comm_delivery_status_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "due_at"]),
            models.Index(fields=["intent", "status"]),
            models.Index(fields=["channel", "status", "due_at"]),
            models.Index(fields=["status", "lease_expires_at"]),
        ]

    def __str__(self) -> str:
        """Return the delivery command identity."""
        return f"{self.snapshot_id}:{self.channel}:{self.status}"


class ParticipantReceipt(CTFBaseModel):
    """Per-recipient in-app read and acknowledgement state."""

    snapshot = models.OneToOneField(RecipientSnapshot, on_delete=models.CASCADE, related_name="receipt")
    read_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        """Django model metadata for one receipt per recipient snapshot."""

        db_table = "ctf_communication_participant_receipt"
        verbose_name = "CTF Participant Receipt"
        verbose_name_plural = "CTF Participant Receipts"

    def __str__(self) -> str:
        """Return the receipt's snapshot identity."""
        return f"receipt:{self.snapshot_id}"
