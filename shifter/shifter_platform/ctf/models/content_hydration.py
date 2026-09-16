"""Persistence evidence for digest-pinned native CTF event content."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from ._base import CTFBaseModel


class CTFContentHydrationReceipt(CTFBaseModel):
    """One bounded hydration identity and drift state per CTF event."""

    class State(models.TextChoices):
        """Whether event content still matches its successful hydration."""

        PRISTINE = "pristine", "Pristine"
        DRIFTED = "drifted", "Drifted"

    event = models.OneToOneField(
        "CTFEvent",
        on_delete=models.CASCADE,
        related_name="content_hydration_receipt",
    )
    scenario_id = models.CharField(max_length=100)
    reference_contract = models.CharField(max_length=100)
    bundle_contract = models.CharField(max_length=100)
    declared_digest = models.CharField(max_length=71)
    object_key_fingerprint = models.CharField(max_length=64)
    object_identity_fingerprint = models.CharField(max_length=64)
    object_size_bytes = models.PositiveIntegerField()
    challenge_count = models.PositiveIntegerField()
    flag_count = models.PositiveIntegerField()
    hint_count = models.PositiveIntegerField()
    prerequisite_count = models.PositiveIntegerField()
    state = models.CharField(
        max_length=16,
        choices=State.choices,
        default=State.PRISTINE,
        db_index=True,
    )
    drift_reason = models.CharField(max_length=64, blank=True, default="")
    drifted_at = models.DateTimeField(null=True, blank=True)
    hydrated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ctf_content_hydrations",
    )
    hydrated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Django model metadata."""

        db_table = "ctf_content_hydration_receipt"
        verbose_name = "CTF content hydration receipt"
        verbose_name_plural = "CTF content hydration receipts"


__all__ = ["CTFContentHydrationReceipt"]
