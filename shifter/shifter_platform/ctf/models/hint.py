"""CTFHint and CTFHintUsage — progressive hint catalog and usage ledger.

Split from monolithic ctf/models.py (PR #856) to satisfy python:S104
(file too large). Public symbols are re-exported by ctf/models/__init__.py
so ``from ctf.models import X`` keeps working unchanged.
"""

from __future__ import annotations

import logging

from django.core.validators import MaxValueValidator
from django.db import models
from django.db.models import Q

from ._base import CTFBaseModel

logger = logging.getLogger(__name__)


class CTFHint(CTFBaseModel):
    """Progressive hint for a CTF challenge.

    Hints are revealed in order. Each hint has its own text and penalty.
    Cumulative penalty = sum of penalties of all unlocked hints.

    Attributes:
        challenge: The challenge this hint belongs to.
        text: The hint text content.
        penalty: Percentage of challenge points deducted for this hint (0-100).
        order: Reveal order (lower = earlier).
    """

    challenge = models.ForeignKey(
        "CTFChallenge",
        on_delete=models.CASCADE,
        related_name="hints",
        help_text="Challenge this hint belongs to",
    )
    text = models.TextField(
        help_text="Hint text content",
    )
    penalty = models.PositiveIntegerField(
        default=0,
        validators=[MaxValueValidator(100)],
        help_text="Percentage of points deducted for using this hint (0-100)",
    )
    order = models.PositiveIntegerField(
        default=0,
        help_text="Reveal order (lower = earlier)",
    )

    class Meta:
        """Django model metadata."""

        db_table = "ctf_hint"
        ordering = ["order", "created_at"]
        verbose_name = "CTF Hint"
        verbose_name_plural = "CTF Hints"
        indexes = [
            models.Index(fields=["challenge", "order"]),
        ]

    def __str__(self) -> str:
        """Return hint description."""
        return f"Hint #{self.order} for {self.challenge.name}"


class CTFHintUsage(CTFBaseModel):
    """Records which hints a participant has unlocked.

    Attributes:
        participant: The participant who unlocked the hint.
        hint: The hint that was unlocked.
        unlocked_at: When the hint was unlocked.
    """

    participant = models.ForeignKey(
        "CTFParticipant",
        on_delete=models.CASCADE,
        related_name="hint_usages",
        help_text="Participant who unlocked the hint",
    )
    hint = models.ForeignKey(
        CTFHint,
        on_delete=models.CASCADE,
        related_name="usages",
        help_text="The hint that was unlocked",
    )
    unlocked_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When the hint was unlocked",
    )

    class Meta:
        """Django model metadata."""

        db_table = "ctf_hint_usage"
        ordering = ["unlocked_at"]
        verbose_name = "CTF Hint Usage"
        verbose_name_plural = "CTF Hint Usages"
        constraints = [
            models.UniqueConstraint(
                fields=["participant", "hint"],
                condition=Q(deleted_at__isnull=True),
                name="unique_active_hint_usage",
            ),
        ]
        indexes = [
            models.Index(fields=["participant", "hint"]),
        ]

    def __str__(self) -> str:
        """Return usage description."""
        return f"{self.participant.name} unlocked {self.hint}"
