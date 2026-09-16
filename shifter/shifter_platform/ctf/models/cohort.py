"""Stable event-owned cohort identity for CTF range selection."""

from __future__ import annotations

from django.db import models
from django.db.models import Q

from ._base import CTFBaseModel


class CTFCohort(CTFBaseModel):
    """An immutable-ID, display-named grouping within one CTF event."""

    event = models.ForeignKey(
        "CTFEvent",
        on_delete=models.CASCADE,
        related_name="cohorts",
        help_text="Event this cohort belongs to",
    )
    name = models.CharField(max_length=100, help_text="Cohort display name")
    description = models.TextField(blank=True, default="")

    class Meta:
        """Persist active cohort names uniquely within an event."""

        db_table = "ctf_cohort"
        ordering = ["name"]
        verbose_name = "CTF Cohort"
        verbose_name_plural = "CTF Cohorts"
        constraints = [
            models.UniqueConstraint(
                fields=["event", "name"],
                condition=Q(deleted_at__isnull=True),
                name="unique_active_cohort_name_per_event",
            ),
        ]

    def __str__(self) -> str:
        return self.name
