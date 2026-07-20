"""Capacity declaration model (CTF-908), split from the engine models module (#561)."""

from __future__ import annotations

from django.db import models


class CapacityDeclaration(models.Model):
    """An event-scoped capacity declaration from an upstream layer (CTF-908).

    The producing layer (CTF) declares how big an upcoming provisioning wave
    is BEFORE spinup begins, so operators and future capacity-aware
    provisioning (PLAT-201) work from declared intent rather than inferring
    it from spinup traffic. Rows are append-only history; the newest row per
    ``event_ref`` is the current declaration. The engine records and surfaces
    these; allocation strategy is intentionally out of scope here (#621).
    """

    source = models.CharField(
        max_length=32,
        default="ctf",
        help_text="Producing layer (currently always 'ctf')",
    )
    event_ref = models.UUIDField(
        db_index=True,
        help_text="Upstream event identifier (opaque to the engine; no FK by design)",
    )
    event_name = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Human-readable event label at declaration time",
    )
    expected_concurrent_ranges = models.PositiveIntegerField(
        help_text="Ranges expected in flight at peak (participants plus spares)",
    )
    cohort_size = models.PositiveIntegerField(
        help_text="Participant cohort size at declaration time",
    )
    window_start = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Expected start of the provisioning/consumption window",
    )
    window_end = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Expected end of the consumption window",
    )
    resource_hints = models.JSONField(
        default=dict,
        blank=True,
        help_text="Shared-resource demand hints (agent mix, NGFW, LLM provider class and rates, ...)",
    )
    declared_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Table metadata."""

        db_table = "engine_capacity_declaration"
        ordering = ["-declared_at"]
        indexes = [
            models.Index(fields=["event_ref", "-declared_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.source}:{self.event_ref} ranges={self.expected_concurrent_ranges} @ {self.declared_at}"
