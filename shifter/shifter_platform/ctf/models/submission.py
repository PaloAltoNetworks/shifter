"""CTFSubmission and CTFAward — flag submissions and organizer awards.

Split from monolithic ctf/models.py (PR #856) to satisfy python:S104
(file too large). Public symbols are re-exported by ctf/models/__init__.py
so ``from ctf.models import X`` keeps working unchanged.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from ._base import CTFBaseModel

logger = logging.getLogger(__name__)


class CTFSubmission(CTFBaseModel):
    """Flag submission attempt by a participant.

    Records all submission attempts for auditing and scoring.

    Attributes:
        participant: The participant who submitted.
        challenge: The challenge being attempted.
        submitted_flag: The flag value submitted.
        is_correct: Whether the submission was correct.
        points_awarded: Points awarded (0 if incorrect).
        attempt_number: Which attempt this is for this challenge.
        ip_address: Client IP address for audit.
        submitted_at: When the submission was made.
    """

    participant = models.ForeignKey(
        "CTFParticipant",
        on_delete=models.CASCADE,
        related_name="submissions",
        help_text="Participant who submitted",
    )
    challenge = models.ForeignKey(
        "CTFChallenge",
        on_delete=models.CASCADE,
        related_name="submissions",
        help_text="Challenge being attempted",
    )
    submitted_flag = models.CharField(
        max_length=500,
        help_text="The flag value submitted (stored for audit)",
    )
    is_correct = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Whether the submission was correct",
    )
    points_awarded = models.PositiveIntegerField(
        default=0,
        help_text="Points awarded for this submission",
    )
    attempt_number = models.PositiveIntegerField(
        default=1,
        help_text="Which attempt this is for this challenge",
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="Client IP address for audit",
    )
    submitted_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="When the submission was made",
    )

    class Meta:
        """Django model metadata."""

        db_table = "ctf_submission"
        ordering = ["-submitted_at"]
        verbose_name = "CTF Submission"
        verbose_name_plural = "CTF Submissions"
        indexes = [
            models.Index(fields=["participant", "challenge"]),
            models.Index(fields=["challenge", "is_correct"]),
            models.Index(fields=["participant", "is_correct"]),
        ]

    def __str__(self) -> str:
        """Return submission description."""
        status = "correct" if self.is_correct else "incorrect"
        return f"{self.participant.name} -> {self.challenge.name}: {status}"

    def clean(self) -> None:
        """Validate submission data."""
        errors: dict[str, list[str]] = {}

        # Validate participant and challenge belong to same event
        if (
            hasattr(self, "participant")
            and hasattr(self, "challenge")
            and self.participant.event_id != self.challenge.event_id
        ):
            errors.setdefault("challenge", []).append("Challenge must belong to participant's event.")

        if errors:
            raise ValidationError(errors)


class CTFAward(CTFBaseModel):
    """Organizer-granted award (bonus or deduction) for a participant.

    Awards allow organizers to adjust participant scores outside of
    normal flag submissions — e.g. bonus points for creative solutions,
    penalties for rule violations, or extra credit tasks.

    Attributes:
        event: The event this award belongs to.
        participant: The participant receiving the award.
        points: Points to add (positive) or deduct (negative).
        reason: Organizer's explanation for the award.
        granted_by: User who granted the award.
    """

    event = models.ForeignKey(
        "CTFEvent",
        on_delete=models.CASCADE,
        related_name="awards",
        help_text="Event this award belongs to",
    )
    participant = models.ForeignKey(
        "CTFParticipant",
        on_delete=models.CASCADE,
        related_name="awards",
        help_text="Participant receiving the award",
    )
    points = models.IntegerField(
        validators=[MinValueValidator(-10000), MaxValueValidator(10000)],
        help_text="Points to add (positive) or deduct (negative)",
    )
    reason = models.TextField(
        help_text="Organizer's explanation for the award",
    )
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ctf_awards_granted",
        help_text="User who granted the award",
    )

    class Meta:
        """Django model metadata."""

        db_table = "ctf_award"
        ordering = ["-created_at"]
        verbose_name = "CTF Award"
        verbose_name_plural = "CTF Awards"
        indexes = [
            models.Index(fields=["event", "participant"]),
            models.Index(fields=["participant"]),
        ]

    def __str__(self) -> str:
        """Return award description."""
        sign = "+" if self.points >= 0 else ""
        return f"Award: {sign}{self.points} pts — {self.reason[:50]}"

    def clean(self) -> None:
        """Validate award data."""
        errors: dict[str, list[str]] = {}

        if (
            hasattr(self, "participant")
            and hasattr(self, "event")
            and self.participant_id
            and self.event_id
            and self.participant.event_id != self.event_id
        ):
            errors.setdefault("participant", []).append("Participant must belong to the same event.")

        if errors:
            raise ValidationError(errors)
