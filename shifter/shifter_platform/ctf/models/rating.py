"""CTFChallengeRating — participant ratings of challenges.

Split from monolithic ctf/models.py (PR #856) to satisfy python:S104
(file too large). Public symbols are re-exported by ctf/models/__init__.py
so ``from ctf.models import X`` keeps working unchanged.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from ._base import CTFBaseModel

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class CTFChallengeRating(CTFBaseModel):
    """Participant rating of a challenge.

    Participants who have solved a challenge can rate it on a 1-5 scale.
    One rating per participant per challenge (upsert on re-rate).

    Attributes:
        participant: The participant who rated.
        challenge: The challenge being rated.
        value: Rating value (1-5).
    """

    participant = models.ForeignKey(
        "CTFParticipant",
        on_delete=models.CASCADE,
        related_name="ratings",
        help_text="Participant who rated",
    )
    challenge = models.ForeignKey(
        "CTFChallenge",
        on_delete=models.CASCADE,
        related_name="ratings",
        help_text="Challenge being rated",
    )
    value = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="Rating value (1-5)",
    )

    class Meta:
        """Django model metadata."""

        db_table = "ctf_challenge_rating"
        ordering = ["-created_at"]
        verbose_name = "CTF Challenge Rating"
        verbose_name_plural = "CTF Challenge Ratings"
        constraints = [
            models.UniqueConstraint(
                fields=["participant", "challenge"],
                condition=Q(deleted_at__isnull=True),
                name="unique_active_rating_per_participant_challenge",
            ),
        ]
        indexes = [
            models.Index(fields=["challenge"]),
        ]

    def __str__(self) -> str:
        """Return rating description."""
        return f"{self.participant.name} rated {self.challenge.name}: {self.value}/5"
