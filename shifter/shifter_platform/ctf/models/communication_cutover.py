"""Durable ownership transfer evidence, never a second delivery queue."""

from __future__ import annotations

from django.db import models


class CommunicationCutover(models.Model):
    """Singleton writer fence; activation is a deliberate maintenance operation."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    fenced_at = models.DateTimeField()
    activated_at = models.DateTimeField(null=True)

    class Meta:
        """Declare the durable cutover table and its database constraints."""

        db_table = "ctf_communication_cutover"
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name="ctf_cutover_singleton")]

    def __str__(self) -> str:
        return "Communication cutover fence"


class LegacyCommunication(models.Model):
    """Stable old-row mapping; historical counters remain on the original row."""

    legacy = models.OneToOneField(
        "ctf.CTFNotification", on_delete=models.CASCADE, primary_key=True, related_name="ledger_mapping"
    )
    campaign = models.OneToOneField(
        "ctf.CommunicationCampaign", on_delete=models.PROTECT, null=True, related_name="legacy_mapping"
    )
    disposition = models.CharField(
        max_length=32,
        choices=[
            ("historical", "Historical aggregate"),
            ("staged", "Staged"),
            ("channel_unavailable", "Channel unavailable"),
            ("transferred", "Transferred"),
        ],
    )
    migrated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Declare the durable cutover table and its database constraints."""

        db_table = "ctf_legacy_communication"

    def __str__(self) -> str:
        return f"Legacy communication {self.pk}: {self.disposition}"
